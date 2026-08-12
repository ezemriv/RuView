#!/usr/bin/env python3
"""Interactively provision one ESP32-S3 without retaining Wi-Fi credentials."""

import argparse
import getpass
import ipaddress
import io
import os
import runpy
import sys
import tempfile
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


TARGET_PORT = "5005"
PROVISIONER_PATH = (
    Path(__file__).resolve().parents[3] / "firmware" / "esp32-csi-node" / "provision.py"
)


def _nonempty(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("SSID must not be empty")
    return value


def _node_id(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("node ID must be an integer in 0..255") from None
    if not 0 <= parsed <= 255:
        raise argparse.ArgumentTypeError("node ID must be in 0..255")
    return parsed


def _literal_ipv4(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        raise argparse.ArgumentTypeError("VPS IP must be a literal IPv4 address") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactively write Wi-Fi and VPS settings to ESP32-S3 NVS only."
    )
    parser.add_argument("--port", required=True, help="Exact serial port, such as /dev/cu.usbserial-0001")
    parser.add_argument("--ssid", required=True, type=_nonempty, help="Wi-Fi SSID")
    parser.add_argument("--vps-ip", required=True, type=_literal_ipv4, help="Literal VPS IPv4 address")
    parser.add_argument("--node-id", required=True, type=_node_id, help="Node ID in 0..255")
    return parser


def _redact(value: str, *sensitive_values: str) -> str:
    """Remove operator-provided credentials from upstream output."""
    for sensitive_value in sensitive_values:
        if sensitive_value:
            value = value.replace(sensitive_value, "[REDACTED]")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Confirm the target, prompt for the secret, and run the upstream NVS writer."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(argument == "--password" or argument.startswith("--password=") for argument in arguments):
        _parser().error("--password is forbidden; enter it only at the hidden prompt")
    args = _parser().parse_args(arguments)
    if sys.stdin is None or not sys.stdin.isatty():
        print("Provisioning requires an interactive terminal on stdin.", file=sys.stderr)
        return 2

    try:
        confirmation = input(f"Retype the exact serial port to confirm {args.port}: ")
    except (EOFError, KeyboardInterrupt):
        print("\nProvisioning cancelled.", file=sys.stderr)
        return 130
    if confirmation != args.port:
        print("Provisioning cancelled: serial-port confirmation did not match.", file=sys.stderr)
        return 1

    try:
        password = getpass.getpass("Wi-Fi password (input hidden): ")
    except (EOFError, KeyboardInterrupt):
        print("\nProvisioning cancelled.", file=sys.stderr)
        return 130

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    result = 0
    try:
        with tempfile.TemporaryDirectory() as state_dir:
            upstream_argv = [
                str(PROVISIONER_PATH),
                "--port",
                args.port,
                "--chip",
                "esp32s3",
                "--ssid",
                args.ssid,
                "--password",
                password,
                "--target-ip",
                args.vps_ip,
                "--target-port",
                TARGET_PORT,
                "--node-id",
                str(args.node_id),
                "--state-dir",
                state_dir,
            ]
            previous_argv = sys.argv
            previous_directory = Path.cwd()
            try:
                sys.argv = upstream_argv
                os.chdir(state_dir)
                with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
                    runpy.run_path(PROVISIONER_PATH, run_name="__main__")
            except SystemExit as error:
                if error.code not in (None, 0):
                    result = 1
            except KeyboardInterrupt:
                result = 130
            except Exception:
                result = 1
            finally:
                os.chdir(previous_directory)
                sys.argv = previous_argv

        print(_redact(captured_stdout.getvalue(), password, args.ssid), end="")
        print(_redact(captured_stderr.getvalue(), password, args.ssid), end="", file=sys.stderr)
        if result == 130:
            print("Provisioning cancelled.", file=sys.stderr)
        elif result != 0:
            print("Provisioning failed; review the redacted output above.", file=sys.stderr)
        return result
    finally:
        del password


if __name__ == "__main__":
    raise SystemExit(main())
