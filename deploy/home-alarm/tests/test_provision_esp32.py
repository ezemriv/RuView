"""Safety tests for the interactive ESP32 provisioning wrapper."""

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "provision_esp32.py"
PROVISIONER_PATH = Path(__file__).resolve().parents[3] / "firmware" / "esp32-csi-node" / "provision.py"


@pytest.fixture
def provision() -> ModuleType:
    """Load the wrapper as a module without executing its CLI entry point."""
    spec = importlib.util.spec_from_file_location("provision_esp32", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_success_invokes_s3_nvs_provisioner_with_private_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provision: ModuleType,
) -> None:
    """A confirmed run passes only the fixed, NVS-only upstream arguments."""
    private_state_dir = tmp_path / "provision-state"
    captured: dict[str, object] = {}

    class TemporaryDirectory:
        def __enter__(self) -> str:
            private_state_dir.mkdir()
            return str(private_state_dir)

        def __exit__(self, *args: object) -> None:
            shutil.rmtree(private_state_dir)
            captured["temporary_directory_closed"] = True

    def run_path(path: Path, *, run_name: str) -> None:
        captured["path"] = path
        captured["run_name"] = run_name
        captured["argv"] = sys.argv.copy()

    monkeypatch.setattr("builtins.input", lambda _prompt: "/dev/cu.usbserial-TEST")
    password_prompts: list[str] = []
    monkeypatch.setattr(
        provision.getpass,
        "getpass",
        lambda prompt: password_prompts.append(prompt) or "test-wifi-secret",
    )
    monkeypatch.setattr(provision.tempfile, "TemporaryDirectory", TemporaryDirectory)
    monkeypatch.setattr(provision.runpy, "run_path", run_path)
    original_argv = ["pytest", "sentinel"]
    monkeypatch.setattr(sys, "argv", original_argv)

    result = provision.main(
        [
            "--port",
            "/dev/cu.usbserial-TEST",
            "--ssid",
            "Home-2G",
            "--vps-ip",
            "203.0.113.10",
            "--node-id",
            "1",
        ]
    )

    assert result == 0
    assert password_prompts == ["Wi-Fi password (input hidden): "]
    assert captured["path"] == PROVISIONER_PATH
    assert captured["run_name"] == "__main__"
    assert captured["argv"] == [
        str(PROVISIONER_PATH),
        "--port",
        "/dev/cu.usbserial-TEST",
        "--chip",
        "esp32s3",
        "--ssid",
        "Home-2G",
        "--password",
        "test-wifi-secret",
        "--target-ip",
        "203.0.113.10",
        "--target-port",
        "5005",
        "--node-id",
        "1",
        "--state-dir",
        str(private_state_dir),
    ]
    assert "write_flash" not in captured["argv"]
    assert "0x9000" not in captured["argv"]
    assert sys.argv is original_argv
    assert captured["temporary_directory_closed"] is True


@pytest.mark.parametrize(
    ("arguments", "error_fragment"),
    [
        (
            ["--port", "/dev/cu.TEST", "--ssid", "", "--vps-ip", "203.0.113.10", "--node-id", "1"],
            "SSID must not be empty",
        ),
        (
            ["--port", "/dev/cu.TEST", "--ssid", "Home", "--vps-ip", "vps.example", "--node-id", "1"],
            "literal IPv4",
        ),
        (
            ["--port", "/dev/cu.TEST", "--ssid", "Home", "--vps-ip", "203.0.113.10", "--node-id", "256"],
            "0..255",
        ),
    ],
)
def test_invalid_values_are_rejected_before_prompting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provision: ModuleType,
    arguments: list[str],
    error_fragment: str,
) -> None:
    """SSID, literal IPv4, and upstream node-ID limits fail at parsing."""
    monkeypatch.setattr("builtins.input", lambda _prompt: pytest.fail("confirmation was prompted"))
    monkeypatch.setattr(
        provision.getpass,
        "getpass",
        lambda _prompt: pytest.fail("password was prompted"),
    )

    with pytest.raises(SystemExit) as error:
        provision.main(arguments)

    assert error.value.code == 2
    assert error_fragment in capsys.readouterr().err


def test_password_cannot_be_passed_on_command_line(
    capsys: pytest.CaptureFixture[str], provision: ModuleType
) -> None:
    """The public CLI has no unattended password-bearing interface."""
    with pytest.raises(SystemExit) as error:
        provision.main(
            [
                "--port",
                "/dev/cu.TEST",
                "--ssid",
                "Home",
                "--vps-ip",
                "203.0.113.10",
                "--node-id",
                "1",
                "--password",
                "must-not-be-accepted",
            ]
        )

    assert error.value.code == 2
    assert "must-not-be-accepted" not in capsys.readouterr().err


def test_port_mismatch_cancels_without_requesting_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provision: ModuleType,
) -> None:
    """Only an exact serial-port retype authorizes provisioning."""
    monkeypatch.setattr("builtins.input", lambda _prompt: "/dev/cu.WRONG")
    monkeypatch.setattr(
        provision.getpass,
        "getpass",
        lambda _prompt: pytest.fail("password was prompted"),
    )
    monkeypatch.setattr(
        provision.runpy,
        "run_path",
        lambda *_args, **_kwargs: pytest.fail("upstream provisioner ran"),
    )

    result = provision.main(
        ["--port", "/dev/cu.TEST", "--ssid", "Home", "--vps-ip", "203.0.113.10", "--node-id", "1"]
    )

    assert result == 1
    assert "cancelled" in capsys.readouterr().err.lower()


def test_keyboard_cancellation_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provision: ModuleType,
) -> None:
    """An operator interrupt cancels without a traceback or provisioning."""

    def cancel(_prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", cancel)
    monkeypatch.setattr(
        provision.runpy,
        "run_path",
        lambda *_args, **_kwargs: pytest.fail("upstream provisioner ran"),
    )

    result = provision.main(
        ["--port", "/dev/cu.TEST", "--ssid", "Home", "--vps-ip", "203.0.113.10", "--node-id", "1"]
    )

    assert result == 130
    assert "cancelled" in capsys.readouterr().err.lower()


def test_upstream_output_and_errors_redact_password_and_restore_argv(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provision: ModuleType,
) -> None:
    """Secrets cannot escape through upstream output, errors, or persistent argv."""
    secret = "uniquely-sensitive-wifi-password"
    original_argv = ["pytest", "sentinel"]
    monkeypatch.setattr(sys, "argv", original_argv)
    monkeypatch.setattr("builtins.input", lambda _prompt: "/dev/cu.TEST")
    monkeypatch.setattr(provision.getpass, "getpass", lambda _prompt: secret)

    def leaking_run_path(_path: Path, *, run_name: str) -> None:
        assert run_name == "__main__"
        print(f"unsafe stdout Home {secret}")
        print(f"unsafe stderr Home {secret}", file=sys.stderr)
        raise RuntimeError(f"unsafe exception {secret}")

    monkeypatch.setattr(provision.runpy, "run_path", leaking_run_path)

    result = provision.main(
        ["--port", "/dev/cu.TEST", "--ssid", "Home", "--vps-ip", "203.0.113.10", "--node-id", "1"]
    )

    output = capsys.readouterr()
    assert result == 1
    assert secret not in output.out
    assert secret not in output.err
    assert "Home" not in output.out
    assert "Home" not in output.err
    assert "[REDACTED]" in output.out
    assert "[REDACTED]" in output.err
    assert "Provisioning failed" in output.err
    assert sys.argv is original_argv


def test_upstream_failure_cannot_leave_nvs_csv_in_operator_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provision: ModuleType,
) -> None:
    """The upstream CSV fallback stays inside the removed private state directory."""
    private_state_dir = tmp_path / "private-state"
    original_directory = Path.cwd()

    class TemporaryDirectory:
        def __enter__(self) -> str:
            private_state_dir.mkdir()
            return str(private_state_dir)

        def __exit__(self, *args: object) -> None:
            shutil.rmtree(private_state_dir)

    monkeypatch.setattr("builtins.input", lambda _prompt: "/dev/cu.TEST")
    monkeypatch.setattr(provision.getpass, "getpass", lambda _prompt: "wifi-password")
    monkeypatch.setattr(provision.tempfile, "TemporaryDirectory", TemporaryDirectory)

    def failed_run_path(_path: Path, *, run_name: str) -> None:
        assert run_name == "__main__"
        assert Path.cwd() == private_state_dir
        Path("nvs_config.csv").write_text("password,wifi-password\n", encoding="utf-8")
        raise RuntimeError("NVS generator failed")

    monkeypatch.setattr(provision.runpy, "run_path", failed_run_path)

    assert provision.main(
        ["--port", "/dev/cu.TEST", "--ssid", "Home", "--vps-ip", "203.0.113.10", "--node-id", "1"]
    ) == 1
    assert Path.cwd() == original_directory
    assert not private_state_dir.exists()
