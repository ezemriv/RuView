"""Tests for deterministic, side-effect-free alarm transitions."""

from ruview_alarm.alarm import AlarmEngine
from ruview_alarm.models import AlarmAction, AlarmEventKind, PersistedState, SensorSample


def healthy(presence: bool, tick: int) -> SensorSample:
    """Build a valid healthy sensor sample."""
    return SensorSample(healthy_esp32=True, presence=presence, tick=tick)


def unhealthy() -> SensorSample:
    """Build a valid unhealthy sensor sample."""
    return SensorSample(healthy_esp32=False)


def test_new_engine_is_disarmed_and_snapshot_retains_offset() -> None:
    """A new service must start disarmed and persist the supplied Telegram offset."""
    engine = AlarmEngine()

    events = engine.command(AlarmAction.STATUS)

    assert [event.kind for event in events] == [AlarmEventKind.STATUS]
    assert "disarmed" in events[0].text
    assert engine.snapshot(7) == PersistedState(armed=False, telegram_offset=7)


def test_restore_armed_is_reported_and_preserves_offset() -> None:
    """A restored armed state must remain armed in status and snapshots."""
    engine = AlarmEngine()
    engine.restore(PersistedState(armed=True, telegram_offset=7))

    events = engine.command(AlarmAction.STATUS)

    assert [event.kind for event in events] == [AlarmEventKind.STATUS]
    assert "armed" in events[0].text
    assert engine.snapshot(8) == PersistedState(armed=True, telegram_offset=8)


def test_arm_and_disarm_are_idempotent_status_commands() -> None:
    """Repeated commands must not open incidents or alter their final armed state."""
    engine = AlarmEngine()

    arm_events = engine.command(AlarmAction.ARM)
    repeated_arm_events = engine.command(AlarmAction.ARM)
    disarm_events = engine.command(AlarmAction.DISARM)
    repeated_disarm_events = engine.command(AlarmAction.DISARM)

    assert [event.kind for event in arm_events] == [AlarmEventKind.STATUS]
    assert "armed" in arm_events[0].text
    assert [event.kind for event in repeated_arm_events] == [AlarmEventKind.STATUS]
    assert "armed" in repeated_arm_events[0].text
    assert [event.kind for event in disarm_events] == [AlarmEventKind.STATUS]
    assert "disarmed" in disarm_events[0].text
    assert [event.kind for event in repeated_disarm_events] == [AlarmEventKind.STATUS]
    assert "disarmed" in repeated_disarm_events[0].text


def test_armed_absent_to_present_opens_one_intrusion() -> None:
    """An armed false-to-true healthy transition must emit exactly one intrusion."""
    engine = AlarmEngine()
    engine.restore(PersistedState(armed=True))

    assert engine.observe(healthy(False, 1), 0.0) == []
    events = engine.observe(healthy(True, 2), 1.0)

    assert [event.kind for event in events] == [AlarmEventKind.INTRUSION]
    assert engine.observe(healthy(True, 3), 2.0) == []


def test_disarmed_presence_never_opens_an_incident() -> None:
    """Presence while disarmed must not produce intrusion or all-clear events."""
    engine = AlarmEngine()

    assert engine.observe(healthy(True, 1), 0.0) == []
    assert engine.observe(healthy(False, 2), 1.0) == []
    assert engine.observe(healthy(False, 3), 61.0) == []


def test_first_healthy_present_sample_after_armed_restart_is_intrusion() -> None:
    """Restoring armed must treat its first healthy present sample as an entry transition."""
    engine = AlarmEngine()
    engine.restore(PersistedState(armed=True))

    events = engine.observe(healthy(True, 1), 0.0)

    assert [event.kind for event in events] == [AlarmEventKind.INTRUSION]


def test_all_clear_requires_60_continuous_seconds_absent() -> None:
    """An incident may clear only after a full uninterrupted healthy absence period."""
    engine = AlarmEngine()
    engine.restore(PersistedState(armed=True))
    engine.observe(healthy(True, 1), 0.0)
    engine.observe(healthy(False, 2), 1.0)

    assert engine.observe(healthy(False, 3), 60.999) == []
    events = engine.observe(healthy(False, 4), 61.0)

    assert [event.kind for event in events] == [AlarmEventKind.ALL_CLEAR]


def test_returning_presence_resets_the_all_clear_timer() -> None:
    """A healthy present sample must restart, rather than continue, the absence countdown."""
    engine = AlarmEngine()
    engine.restore(PersistedState(armed=True))
    engine.observe(healthy(True, 1), 0.0)
    engine.observe(healthy(False, 2), 1.0)
    engine.observe(healthy(True, 3), 30.0)
    engine.observe(healthy(False, 4), 31.0)

    assert engine.observe(healthy(False, 5), 90.999) == []
    events = engine.observe(healthy(False, 6), 91.0)

    assert [event.kind for event in events] == [AlarmEventKind.ALL_CLEAR]


def test_offline_and_recovery_are_emitted_once_at_their_boundaries() -> None:
    """Thirty unhealthy seconds trigger one offline event and one later recovery."""
    engine = AlarmEngine()

    assert engine.observe(unhealthy(), 0.0) == []
    assert engine.observe(unhealthy(), 29.999) == []
    events = engine.observe(unhealthy(), 30.0)
    assert [event.kind for event in events] == [AlarmEventKind.SENSOR_OFFLINE]
    assert engine.observe(unhealthy(), 31.0) == []
    recovered = engine.observe(healthy(False, 1), 32.0)
    assert [event.kind for event in recovered] == [AlarmEventKind.SENSOR_RECOVERED]
    assert engine.observe(healthy(False, 2), 33.0) == []


def test_unhealthy_samples_do_not_change_presence_transition_tracking() -> None:
    """Unhealthy input must not erase the last healthy presence state."""
    engine = AlarmEngine()
    engine.restore(PersistedState(armed=True))
    engine.observe(healthy(False, 1), 0.0)
    engine.observe(unhealthy(), 1.0)

    events = engine.observe(healthy(True, 2), 2.0)

    assert [event.kind for event in events] == [AlarmEventKind.INTRUSION]


def test_disarm_closes_an_incident_and_cancels_its_countdown() -> None:
    """Disarming during an incident must prevent a later all-clear notification."""
    engine = AlarmEngine()
    engine.restore(PersistedState(armed=True))
    engine.observe(healthy(True, 1), 0.0)
    engine.observe(healthy(False, 2), 1.0)

    engine.command(AlarmAction.DISARM)

    assert engine.observe(healthy(False, 3), 61.0) == []
