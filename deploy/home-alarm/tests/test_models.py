import pytest
from pydantic import ValidationError

from ruview_alarm.models import AlarmAction, PersistedState, SensorSample


def test_persisted_state_has_exact_versioned_shape() -> None:
    """Persisted state must retain its stable, versioned storage contract."""
    state = PersistedState(armed=True, telegram_offset=123456789)

    assert state.model_dump() == {
        "version": 1,
        "armed": True,
        "telegram_offset": 123456789,
    }


def test_sensor_sample_rejects_presence_without_healthy_esp32() -> None:
    """An unhealthy source must not contribute sensing values."""
    with pytest.raises(ValidationError, match="unhealthy samples cannot carry sensing data"):
        SensorSample(healthy_esp32=False, presence=True)


def test_alarm_action_accepts_only_arm_disarm_status() -> None:
    """Unsupported Telegram actions must be rejected at the boundary."""
    assert {action.value for action in AlarmAction} == {"arm", "disarm", "status"}

    with pytest.raises(ValueError):
        AlarmAction("silence")
