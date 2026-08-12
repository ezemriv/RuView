"""Tests for the alarm service heartbeat contract."""

import json
import os
from pathlib import Path

import pytest

from ruview_alarm.healthcheck import check_health, write_heartbeat


def fresh_snapshot(now: float = 1_000.0) -> dict[str, float]:
    """Return a complete fresh heartbeat snapshot."""
    return {
        "main": now,
        "sensing": now,
        "telegram": now,
        "notifications": now,
    }


def test_write_heartbeat_atomically_publishes_all_required_utc_epochs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader must see one complete snapshot after an atomic replacement."""
    path = tmp_path / "health" / "alarm.json"
    original_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def track_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        replacements.append((source_path, destination_path))
        assert source_path.parent == path.parent
        assert not destination_path.exists()
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", track_replace)

    write_heartbeat(path, fresh_snapshot())

    assert replacements[0][1] == path
    assert json.loads(path.read_text(encoding="utf-8")) == fresh_snapshot()


def test_check_health_accepts_a_complete_fresh_snapshot(tmp_path: Path) -> None:
    """All four live loops make the Docker health check succeed."""
    path = tmp_path / "health.json"
    write_heartbeat(path, fresh_snapshot())

    assert check_health(path, now=1_000.0) == 0


@pytest.mark.parametrize(
    ("loop_name", "age"),
    [("main", 45.001), ("sensing", 45.001), ("notifications", 45.001), ("telegram", 60.001)],
)
def test_check_health_rejects_stale_loop_heartbeats(
    tmp_path: Path, loop_name: str, age: float
) -> None:
    """Each loop must remain inside its explicit freshness threshold."""
    path = tmp_path / "health.json"
    snapshot = fresh_snapshot()
    snapshot[loop_name] = 1_000.0 - age
    write_heartbeat(path, snapshot)

    assert check_health(path, now=1_000.0) == 1


@pytest.mark.parametrize(
    "contents",
    [
        "{not-json}",
        "[]",
        '{"main":1000,"sensing":1000,"telegram":1000}',
        '{"main":1000,"sensing":1000,"telegram":1000,"notifications":1000,"extra":1000}',
        '{"main":true,"sensing":1000,"telegram":1000,"notifications":1000}',
        '{"main":NaN,"sensing":1000,"telegram":1000,"notifications":1000}',
        '{"main":1001,"sensing":1000,"telegram":1000,"notifications":1000}',
        '{"main":1000,"main":1000,"sensing":1000,"telegram":1000,"notifications":1000}',
    ],
)
def test_check_health_rejects_non_strict_or_incomplete_json(
    tmp_path: Path, contents: str
) -> None:
    """Malformed, ambiguous, future, or schema-invalid health data must fail closed."""
    path = tmp_path / "health.json"
    path.write_text(contents, encoding="utf-8")

    assert check_health(path, now=1_000.0) == 1


def test_check_health_rejects_a_missing_file(tmp_path: Path) -> None:
    """No published heartbeat means the process is not healthy."""
    assert check_health(tmp_path / "missing.json", now=1_000.0) == 1


def test_check_health_rejects_hostile_unbounded_integer_without_raising(tmp_path: Path) -> None:
    """An unbounded JSON integer must fail closed rather than crash the health process."""
    path = tmp_path / "health.json"
    path.write_text(
        '{"main":' + "9" * 1_000 + ',"sensing":1000,"telegram":1000,"notifications":1000}',
        encoding="utf-8",
    )

    assert check_health(path, now=1_000.0) == 1
