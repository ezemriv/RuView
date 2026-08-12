"""Durable storage for the alarm's restart-safe state."""

import os
import tempfile
from pathlib import Path

from ruview_alarm.models import PersistedState


def load_state(path: Path) -> PersistedState:
    """Load strict persisted state, defaulting only when no file exists."""
    if not path.exists():
        return PersistedState()
    return PersistedState.model_validate_json(path.read_bytes())


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
