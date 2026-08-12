"""Pure transition engine for the RuView home alarm."""

from ruview_alarm.models import AlarmAction, AlarmEvent, AlarmEventKind, PersistedState, SensorSample


class AlarmEngine:
    """Convert alarm commands and sensor samples into deterministic events."""

    def __init__(self, *, all_clear_seconds: float = 60.0, offline_seconds: float = 30.0) -> None:
        """Start a new, disarmed alarm instance."""
        self._all_clear_seconds = all_clear_seconds
        self._offline_seconds = offline_seconds
        self._armed = False
        self._previous_healthy_presence = False
        self._active_incident = False
        self._absence_started_at: float | None = None
        self._unhealthy_started_at: float | None = None
        self._offline_notified = False

    def restore(self, state: PersistedState) -> None:
        """Restore durable state while resetting non-durable transition tracking."""
        self._armed = state.armed
        self._previous_healthy_presence = False
        self._active_incident = False
        self._absence_started_at = None
        self._unhealthy_started_at = None
        self._offline_notified = False

    def command(self, action: AlarmAction) -> list[AlarmEvent]:
        """Apply an alarm command and report the resulting arm state."""
        if action is AlarmAction.ARM:
            if not self._armed:
                self._active_incident = False
                self._absence_started_at = None
            self._armed = True
            self._previous_healthy_presence = False
        elif action is AlarmAction.DISARM:
            self._armed = False
            self._active_incident = False
            self._absence_started_at = None

        return [self._status_event()]

    def observe(self, sample: SensorSample, now: float) -> list[AlarmEvent]:
        """Apply a health and presence sample at a monotonic time."""
        if not sample.healthy_esp32:
            self._absence_started_at = None
            return self._observe_unhealthy(now)

        events = self._observe_healthy()
        presence = sample.presence is True

        if self._armed and presence and not self._previous_healthy_presence and not self._active_incident:
            events.append(self._event(AlarmEventKind.INTRUSION, "Intrusion detected while armed."))
            self._active_incident = True
            self._absence_started_at = None
        elif self._active_incident:
            if presence:
                self._absence_started_at = None
            elif self._absence_started_at is None:
                self._absence_started_at = now
            elif now - self._absence_started_at >= self._all_clear_seconds:
                events.append(self._event(AlarmEventKind.ALL_CLEAR, "All clear after continuous absence."))
                self._active_incident = False
                self._absence_started_at = None

        self._previous_healthy_presence = presence
        return events

    def snapshot(self, offset: int | None) -> PersistedState:
        """Return the durable state with the supplied Telegram poll offset."""
        return PersistedState(armed=self._armed, telegram_offset=offset)

    def _observe_unhealthy(self, now: float) -> list[AlarmEvent]:
        if self._unhealthy_started_at is None:
            self._unhealthy_started_at = now
        elif now - self._unhealthy_started_at >= self._offline_seconds and not self._offline_notified:
            self._offline_notified = True
            return [self._event(AlarmEventKind.SENSOR_OFFLINE, "Sensor is offline.")]
        return []

    def _observe_healthy(self) -> list[AlarmEvent]:
        self._unhealthy_started_at = None
        if not self._offline_notified:
            return []
        self._offline_notified = False
        return [self._event(AlarmEventKind.SENSOR_RECOVERED, "Sensor recovered.")]

    def _status_event(self) -> AlarmEvent:
        state = "armed" if self._armed else "disarmed"
        return self._event(AlarmEventKind.STATUS, f"Alarm is {state}.")

    @staticmethod
    def _event(kind: AlarmEventKind, text: str) -> AlarmEvent:
        return AlarmEvent(kind=kind, text=text)
