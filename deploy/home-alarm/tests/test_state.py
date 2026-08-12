"""Tests for durable alarm-state storage."""

import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from ruview_alarm.models import PersistedState
from ruview_alarm.state import load_state, save_state


def test_missing_file_returns_default_state(tmp_path: Path) -> None:
    """A first start must use the unarmed, no-offset state."""
    assert load_state(tmp_path / "missing.json") == PersistedState()


def test_round_trip_restores_armed_and_offset(tmp_path: Path) -> None:
    """Saved state must survive a restart unchanged."""
    path = tmp_path / "state.json"
    expected = PersistedState(armed=True, telegram_offset=42)

    save_state(path, expected)

    assert load_state(path) == expected


def test_save_replaces_a_private_temporary_file_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Save must publish only a private temporary file via replacement."""
    path = tmp_path / "state.json"
    original_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def assert_atomic_replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        replacements.append((source_path, destination_path))
        assert source_path.parent == path.parent
        assert source_path.name.endswith(".tmp")
        assert not destination_path.exists()
        assert stat.S_IMODE(source_path.stat().st_mode) == 0o600
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", assert_atomic_replace)

    save_state(path, PersistedState(armed=True))

    assert len(replacements) == 1
    assert replacements[0][1] == path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_fsyncs_file_and_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Save must durably flush the data file and its directory entry."""
    path = tmp_path / "private" / "state.json"
    original_fsync = os.fsync
    descriptor_kinds: list[int] = []

    def track_fsync(fd: int) -> None:
        descriptor_kinds.append(stat.S_IFMT(os.fstat(fd).st_mode))
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", track_fsync)

    save_state(path, PersistedState())

    assert stat.S_IFREG in descriptor_kinds
    assert stat.S_IFDIR in descriptor_kinds


def test_load_rejects_corrupt_json(tmp_path: Path) -> None:
    """Corrupt on-disk data must halt startup instead of silently resetting state."""
    path = tmp_path / "state.json"
    path.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_state(path)


def test_load_rejects_unsupported_version(tmp_path: Path) -> None:
    """State from an unknown schema version must not be accepted."""
    path = tmp_path / "state.json"
    path.write_text('{"version":2,"armed":false,"telegram_offset":null}\n', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_state(path)


def test_load_rejects_extra_fields(tmp_path: Path) -> None:
    """Unexpected state fields must not be ignored during restoration."""
    path = tmp_path / "state.json"
    path.write_text(
        '{"version":1,"armed":false,"telegram_offset":null,"unknown":true}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_state(path)


@pytest.mark.parametrize(
    "payload",
    [
        '{"version":1,"armed":false}',
        '{"version":1,"telegram_offset":null}',
        '{"armed":false,"telegram_offset":null}',
        '{"version":1,"armed":"false","telegram_offset":null}',
        '{"version":1,"armed":false,"telegram_offset":"7"}',
        '{"version":true,"armed":false,"telegram_offset":null}',
    ],
)
def test_load_rejects_missing_or_coercive_state_fields(tmp_path: Path, payload: str) -> None:
    """Every persisted field must be present with its exact JSON type."""
    path = tmp_path / "state.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        load_state(path)


def test_load_rejects_duplicate_state_keys(tmp_path: Path) -> None:
    """A later duplicate member must never override an earlier durable value."""
    path = tmp_path / "state.json"
    path.write_text(
        '{"version":1,"armed":true,"armed":false,"telegram_offset":7}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_state(path)
