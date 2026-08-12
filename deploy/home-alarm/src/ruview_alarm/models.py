"""Shared validated data contracts for the RuView home alarm service."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlarmAction(StrEnum):
    """Actions accepted from the alarm control channel."""

    ARM = "arm"
    DISARM = "disarm"
    STATUS = "status"


class AlarmEventKind(StrEnum):
    """Kinds of events emitted by the alarm service."""

    STATUS = "status"
    INTRUSION = "intrusion"
    ALL_CLEAR = "all_clear"
    SENSOR_OFFLINE = "sensor_offline"
    SENSOR_RECOVERED = "sensor_recovered"


class PersistedState(BaseModel):
    """Versioned service state stored on disk."""

    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    armed: bool = False
    telegram_offset: int | None = Field(default=None, ge=0)


class SensorSample(BaseModel):
    """A health and sensing observation from the ESP32 source."""

    healthy_esp32: bool
    presence: bool | None = None
    tick: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_presence_only_for_healthy_source(self) -> Self:
        """Prevent stale or malformed sensing data from unhealthy sources."""
        if not self.healthy_esp32 and (self.presence is not None or self.tick is not None):
            raise ValueError("unhealthy samples cannot carry sensing data")
        return self


class TelegramUpdate(BaseModel):
    """A normalized Telegram poll result."""

    update_id: int = Field(ge=0)
    chat_id: int | None = None
    action: AlarmAction | None = None
    callback_id: str | None = None


class AlarmEvent(BaseModel):
    """An event the alarm service can report to its users."""

    kind: AlarmEventKind
    text: str
