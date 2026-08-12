"""Atomic heartbeat publication and fail-closed Docker health validation."""

import json
import math
import os
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_REQUIRED_LOOPS = frozenset({"main", "sensing", "telegram", "notifications"})
_MAX_AGES = {
    "main": 45.0,
    "sensing": 45.0,
    "telegram": 60.0,
    "notifications": 45.0,
}


def write_heartbeat(path: Path, snapshot: Mapping[str, float]) -> None:
    """Atomically publish a complete heartbeat snapshot as UTC epoch seconds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            fd = -1
            json.dump(dict(snapshot), file, allow_nan=False, sort_keys=True, separators=(",", ":"))
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if fd != -1:
            os.close(fd)
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def check_health(path: Path, now: float) -> int:
    """Return zero only for strict, complete, and fresh heartbeat JSON."""
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return 1

    if not isinstance(payload, dict) or set(payload) != _REQUIRED_LOOPS:
        return 1
    for name, maximum_age in _MAX_AGES.items():
        timestamp = payload[name]
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            return 1
        if not math.isfinite(timestamp) or timestamp > now or now - timestamp > maximum_age:
            return 1
    return 0


def _reject_constant(value: str) -> Any:
    """Reject JSON's non-standard NaN and Infinity extensions."""
    raise ValueError(value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate object keys instead of silently taking the last value."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def main() -> int:
    """Validate the default service heartbeat for a container health check."""
    return check_health(Path("/tmp/ruview-alarm-health.json"), time.time())


if __name__ == "__main__":
    raise SystemExit(main())
