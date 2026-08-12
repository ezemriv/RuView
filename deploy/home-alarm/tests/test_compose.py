"""Production Docker Compose contract tests for the home alarm."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ENV = PROJECT_ROOT / "tests" / "fixtures" / "compose.env"
REQUIRED_ENVIRONMENT = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "RUVIEW_API_TOKEN",
    "RUVIEW_UDP_ALLOW",
)
SENSING_IMAGE = (
    "docker.io/ruvnet/wifi-densepose@"
    "sha256:fac235102bebc8a9bfc5445645bc6908d02cf0244154e59b7bab297a574b5fae"
)


def _compose_config(env_file: Path) -> tuple[dict[str, Any], str]:
    environment = os.environ.copy()
    for name in REQUIRED_ENVIRONMENT:
        environment.pop(name, None)
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "config",
            "--format",
            "json",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result.stdout


def test_compose_pins_sensing_boundary_and_only_publishes_approved_ports() -> None:
    config, rendered = _compose_config(FIXTURE_ENV)
    sensing = config["services"]["sensing-server"]

    assert sensing["image"] == SENSING_IMAGE
    assert sensing["ports"] == [
        {
            "target": 3000,
            "published": "3000",
            "host_ip": "127.0.0.1",
            "protocol": "tcp",
            "mode": "ingress",
        },
        {
            "target": 5005,
            "published": "5005",
            "protocol": "udp",
            "mode": "ingress",
        },
    ]
    assert sensing["environment"]["CSI_SOURCE"] == "esp32"
    assert sensing["environment"]["RUVIEW_UDP_BIND"] == "0.0.0.0"
    assert sensing["environment"]["RUVIEW_UDP_ALLOW"] == "198.51.100.42/32"
    assert "3001" not in rendered


def test_both_services_have_the_required_runtime_hardening() -> None:
    config, _ = _compose_config(FIXTURE_ENV)

    assert set(config["services"]) == {"sensing-server", "telegram-alarm"}
    assert set(config["networks"]) == {"alarm-net"}
    assert set(config["volumes"]) == {"alarm-state"}
    for service in config["services"].values():
        assert service["restart"] == "unless-stopped"
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["networks"] == {"alarm-net": None}
        assert service["healthcheck"]["test"]


def test_alarm_service_is_non_root_read_only_and_uses_only_expected_writable_mounts() -> None:
    config, _ = _compose_config(FIXTURE_ENV)
    alarm = config["services"]["telegram-alarm"]

    assert alarm["user"] == "10001:10001"
    assert alarm["read_only"] is True
    assert len(alarm["tmpfs"]) == 1
    assert alarm["tmpfs"][0].split(":", maxsplit=1)[0] == "/tmp"
    assert alarm["volumes"] == [
        {
            "type": "volume",
            "source": "alarm-state",
            "target": "/data",
            "volume": {},
        }
    ]
    assert alarm["depends_on"] == {
        "sensing-server": {"condition": "service_healthy", "required": True}
    }


@pytest.mark.parametrize("missing_name", REQUIRED_ENVIRONMENT)
def test_compose_rejects_each_missing_required_environment_variable(
    tmp_path: Path, missing_name: str
) -> None:
    values = {
        "TELEGRAM_BOT_TOKEN": "replace-with-telegram-bot-token",
        "TELEGRAM_CHAT_ID": "123456789",
        "RUVIEW_API_TOKEN": "replace-with-a-distinct-ruview-api-token",
        "RUVIEW_UDP_ALLOW": "198.51.100.42/32",
    }
    values.pop(missing_name)
    env_file = tmp_path / "compose.env"
    env_file.write_text(
        "".join(f"{name}={value}\n" for name, value in values.items()), encoding="utf-8"
    )

    environment = os.environ.copy()
    for name in REQUIRED_ENVIRONMENT:
        environment.pop(name, None)
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "config", "--quiet"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert missing_name in result.stderr


def test_generated_secrets_exist_only_in_runtime_environment(
    tmp_path: Path,
) -> None:
    telegram_token = _sentinel("telegram")
    ruview_token = _sentinel("ruview")
    env_file = tmp_path / "compose.env"
    env_file.write_text(
        "\n".join(
            (
                f"TELEGRAM_BOT_TOKEN={telegram_token}",
                "TELEGRAM_CHAT_ID=987654321",
                f"RUVIEW_API_TOKEN={ruview_token}",
                "RUVIEW_UDP_ALLOW=198.51.100.42/32",
                "",
            )
        ),
        encoding="utf-8",
    )

    config, _ = _compose_config(env_file)
    assert _string_paths(config, telegram_token) == [
        ("services", "telegram-alarm", "environment", "TELEGRAM_BOT_TOKEN")
    ]
    assert _string_paths(config, ruview_token) == [
        ("services", "sensing-server", "environment", "RUVIEW_API_TOKEN"),
        ("services", "telegram-alarm", "environment", "RUVIEW_API_TOKEN"),
    ]

    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or _is_generated_path(path):
            continue
        contents = path.read_bytes()
        assert telegram_token.encode() not in contents, path
        assert ruview_token.encode() not in contents, path


def _sentinel(label: str) -> str:
    return "_".join(("compose", label, "process", "9f8e7d6c"))


def _string_paths(value: Any, needle: str, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    matches: list[tuple[str, ...]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            matches.extend(_string_paths(child, needle, (*path, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(_string_paths(child, needle, (*path, str(index))))
    elif isinstance(value, str) and needle in value:
        matches.append(path)
    return matches


def _is_generated_path(path: Path) -> bool:
    relative_parts = path.relative_to(PROJECT_ROOT).parts
    return any(
        part in {".git", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}
        for part in relative_parts
    )
