"""Level 3 recovery smoke test using the production image and Compose graph."""

import json
from io import BytesIO
import os
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (PROJECT_ROOT / "compose.yaml", PROJECT_ROOT / "compose.smoke.yaml")
RUVIEW_IMAGE = (
    "docker.io/ruvnet/wifi-densepose@"
    "sha256:fac235102bebc8a9bfc5445645bc6908d02cf0244154e59b7bab297a574b5fae"
)
FAKE_TELEGRAM_IMAGE = "python:3.12-slim"
_MAX_RESPONSE_BYTES = 1_048_576


def _run(
    command: list[str], *, environment: dict[str, str], check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        pytest.fail(f"command failed ({result.returncode}): {command!r}\n{result.stderr}")
    return result


def _compose(
    project: str, environment: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose"]
    for path in COMPOSE_FILES:
        command.extend(("-f", str(path)))
    command.extend(("--project-name", project, *arguments))
    return _run(command, environment=environment)


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=2.0) as response:  # noqa: S310 - fixed loopback URLs
            return _response_result(response.status, response)
    except HTTPError as error:
        return _response_result(error.code, error)


def _response_result(status: int, response: Any) -> tuple[int, Any]:
    """Return status plus bounded JSON or safely decoded text."""
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    truncated = len(body) > _MAX_RESPONSE_BYTES
    text = body[:_MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")
    if truncated:
        text += "…[truncated]"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = text
    return status, payload


def test_plain_text_http_error_body_preserves_status() -> None:
    """A non-JSON upstream 401 body must not hide its authorization status."""
    error = HTTPError(
        "http://127.0.0.1/api/v1/sensing/latest",
        401,
        "Unauthorized",
        {},
        BytesIO(b"missing or invalid bearer token\n"),
    )

    assert _response_result(error.code, error) == (
        401,
        "missing or invalid bearer token\n",
    )


def _wait_until(check: Callable[[], bool], *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (HTTPError, URLError, ConnectionError, TimeoutError) as error:
            last_error = error
        time.sleep(0.25)
    raise AssertionError(f"condition not met before timeout; last error: {last_error!r}")


def _inspect_json(target_type: str, target: str, environment: dict[str, str]) -> dict[str, Any]:
    result = _run(
        ["docker", target_type, "inspect", target],
        environment=environment,
    )
    return json.loads(result.stdout)[0]


def _loopback_port(container: dict[str, Any], container_port: str) -> int:
    """Return one ephemeral loopback host port and reject broader publications."""
    bindings = container["NetworkSettings"]["Ports"][container_port]
    assert len(bindings) == 1
    assert bindings[0]["HostIp"] == "127.0.0.1"
    host_port = int(bindings[0]["HostPort"])
    assert host_port > 0
    return host_port


def test_smoke_compose_builds_only_the_alarm_image() -> None:
    """The fake service must not race the alarm build for the same image tag."""
    environment = os.environ.copy()
    environment.update(
        {
            "ALARM_IMAGE": "ruview/home-alarm-smoke:test",
            "TELEGRAM_BOT_TOKEN": "telegram-smoke-config-sentinel",
            "TELEGRAM_CHAT_ID": "246810",
            "RUVIEW_API_TOKEN": "ruview-smoke-config-sentinel",
            "RUVIEW_UDP_ALLOW": "198.51.100.42/32",
        }
    )

    rendered = _compose("ruview-alarm-smoke-config", environment, "config", "--format", "json")
    services = json.loads(rendered.stdout)["services"]

    assert services["telegram-alarm"]["image"] == "ruview/home-alarm-smoke:test"
    assert services["telegram-alarm"]["build"]
    assert services["telegram-fake"]["image"] == FAKE_TELEGRAM_IMAGE
    assert "build" not in services["telegram-fake"]
    assert services["sensing-server"]["ports"] == [
        {
            "host_ip": "127.0.0.1",
            "mode": "ingress",
            "protocol": "tcp",
            "published": "0",
            "target": 3000,
        }
    ]
    assert services["telegram-fake"]["ports"] == [
        {
            "host_ip": "127.0.0.1",
            "mode": "ingress",
            "protocol": "tcp",
            "published": "0",
            "target": 8080,
        }
    ]


@pytest.mark.container
def test_container_recreation_preserves_arm_state_without_weakening_source_auth() -> None:
    """Verify API auth and durable Telegram state while simulation stays non-ESP32."""
    environment = os.environ.copy()
    daemon = _run(["docker", "info"], environment=environment, check=False)
    if daemon.returncode != 0:
        pytest.skip("Level 3 gate unmet: Docker daemon unavailable")

    project = f"ruview-alarm-smoke-{uuid.uuid4().hex[:12]}"
    telegram_sentinel = f"telegram-smoke-{uuid.uuid4().hex}"
    ruview_sentinel = f"ruview-smoke-{uuid.uuid4().hex}"
    alarm_image = f"{project}-alarm:test"
    environment.update(
        {
            "ALARM_IMAGE": alarm_image,
            "TELEGRAM_BOT_TOKEN": telegram_sentinel,
            "TELEGRAM_CHAT_ID": "246810",
            "RUVIEW_API_TOKEN": ruview_sentinel,
            "RUVIEW_UDP_ALLOW": "198.51.100.42/32",
        }
    )

    try:
        _compose(project, environment, "up", "-d", "--build", "--wait", "--wait-timeout", "120")

        sensing_id = _compose(project, environment, "ps", "-q", "sensing-server").stdout.strip()
        sensing = _inspect_json("container", sensing_id, environment)
        sensing_port = _loopback_port(sensing, "3000/tcp")
        telegram_fake_id = _compose(
            project, environment, "ps", "-q", "telegram-fake"
        ).stdout.strip()
        telegram_fake = _inspect_json("container", telegram_fake_id, environment)
        telegram_fake_port = _loopback_port(telegram_fake, "8080/tcp")
        sensing_url = f"http://127.0.0.1:{sensing_port}"
        telegram_fake_url = f"http://127.0.0.1:{telegram_fake_port}"

        def authenticated_latest_is_available() -> bool:
            status, _ = _request_json(
                f"{sensing_url}/api/v1/sensing/latest",
                headers={"Authorization": f"Bearer {ruview_sentinel}"},
            )
            return status == 200

        _wait_until(authenticated_latest_is_available)
        unauthorized_status, _ = _request_json(f"{sensing_url}/api/v1/sensing/latest")
        assert unauthorized_status == 401

        assert sensing["Config"]["Image"] == RUVIEW_IMAGE
        assert sensing["Config"]["Env"] is not None
        assert "CSI_SOURCE=simulated" in sensing["Config"]["Env"]
        assert sensing["Config"]["Healthcheck"]["Test"] == ["CMD-SHELL", "kill -0 1"]
        assert set(sensing["NetworkSettings"]["Ports"]) == {"3000/tcp"}
        assert "3001/tcp" not in sensing["NetworkSettings"]["Ports"]
        assert "5005/udp" not in sensing["NetworkSettings"]["Ports"]
        assert set(telegram_fake["NetworkSettings"]["Ports"]) == {"8080/tcp"}

        update = {
            "update_id": 1,
            "message": {"chat": {"id": 246810}, "text": "/arm"},
        }
        status, _ = _request_json(f"{telegram_fake_url}/enqueue", method="POST", payload=update)
        assert status == 200

        def alarm_is_armed() -> bool:
            _, observations = _request_json(f"{telegram_fake_url}/messages")
            return "Alarm is armed." in observations["messages"]

        _wait_until(alarm_is_armed)
        before_recreate = _compose(
            project,
            environment,
            "exec",
            "-T",
            "telegram-alarm",
            "/bin/sh",
            "-c",
            "cat /data/state.json",
        )
        assert json.loads(before_recreate.stdout) == {
            "version": 1,
            "armed": True,
            "telegram_offset": 2,
        }

        _compose(
            project,
            environment,
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "telegram-alarm",
        )

        def restored_arm_is_reported() -> bool:
            _, observations = _request_json(f"{telegram_fake_url}/messages")
            return observations["messages"].count("Alarm restored: armed") == 1

        _wait_until(restored_arm_is_reported)
        after_recreate = _compose(
            project,
            environment,
            "exec",
            "-T",
            "telegram-alarm",
            "/bin/sh",
            "-c",
            "cat /data/state.json",
        )
        assert json.loads(after_recreate.stdout)["armed"] is True

        image = _inspect_json("image", alarm_image, environment)
        config = image["Config"]
        assert config["User"] == "10001:10001"
        assert config["Cmd"] == ["/app/.venv/bin/python", "-m", "ruview_alarm"]
        assert config["Healthcheck"]["Test"] == [
            "CMD",
            "/app/.venv/bin/python",
            "-m",
            "ruview_alarm.healthcheck",
        ]
        history = _run(
            ["docker", "history", "--no-trunc", "--format", "{{json .}}", alarm_image],
            environment=environment,
        ).stdout
        serialized_config = json.dumps(config, sort_keys=True)
        for sentinel in (telegram_sentinel, ruview_sentinel):
            assert sentinel not in serialized_config
            assert sentinel not in history
    finally:
        _compose(project, environment, "down", "--volumes", "--remove-orphans")
