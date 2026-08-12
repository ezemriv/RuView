"""Durable storage for the alarm's restart-safe state."""

import json
import os
import tempfile
from pathlib import Path

from ruview_alarm.models import PersistedState

_STATE_KEYS = {"version", "armed", "telegram_offset"}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError(f"duplicate persisted-state key: {key}")
        parsed[key] = value
    return parsed


def load_state(path: Path) -> PersistedState:
    """Load strict persisted state, defaulting only when no file exists."""
    if not path.exists():
        return PersistedState()

    encoded = path.read_bytes()
    try:
        payload = json.loads(encoded, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError:
        return PersistedState.model_validate_json(encoded, strict=True)

    state = PersistedState.model_validate(payload, strict=True)
    if not isinstance(payload, dict) or set(payload) != _STATE_KEYS:
        raise ValueError("persisted state must contain exactly the supported keys")
    if type(payload["version"]) is not int or type(payload["armed"]) is not bool:
        raise ValueError("persisted state fields must use exact JSON types")
    offset = payload["telegram_offset"]
    if offset is not None and type(offset) is not int:
        raise ValueError("persisted state fields must use exact JSON types")
    return state


def save_state(path: Path, state: PersistedState) -> None:
    """Atomically save state with private permissions and durability barriers."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as file:
            fd = -1
            file.write(state.model_dump_json().encode("utf-8") + b"\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)

        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if fd != -1:
            os.close(fd)
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
