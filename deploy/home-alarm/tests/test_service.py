"""Tests for supervised alarm service orchestration."""

import asyncio
import itertools
import logging
import time
from contextlib import suppress
from pathlib import Path

import httpx
import pytest

from ruview_alarm import __main__ as process_entry
from ruview_alarm.config import Settings
from ruview_alarm.models import AlarmAction, PersistedState, SensorSample, TelegramUpdate
from ruview_alarm.ruview import RuViewError
from ruview_alarm.service import AlarmService, retry_delays, run_alarm
from ruview_alarm.telegram import TelegramError


def settings_for(tmp_path: Path) -> Settings:
    """Build valid isolated settings."""
    return Settings(
        telegram_bot_token="telegram-test-token",
        telegram_chat_id=123,
        ruview_api_token="ruview-test-token",
        state_path=tmp_path / "state.json",
        health_path=tmp_path / "health.json",
    )


async def cancel(task: asyncio.Task[None]) -> None:
    """Cancel one running service task and consume its cancellation."""
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


class BlockingRuView:
    """Record one sample attempt, then remain cancellably in flight."""

    def __init__(self) -> None:
        self.sampled = asyncio.Event()
        self._block = asyncio.Event()

    async def sample(self) -> SensorSample:
        """Signal polling and block."""
        self.sampled.set()
        await self._block.wait()
        raise AssertionError("unreachable")


class BlockingTelegram:
    """Capture delivery while long polling remains cancellably in flight."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.message_sent = asyncio.Event()
        self.polled = asyncio.Event()
        self._block = asyncio.Event()

    async def get_updates(self, offset: int, timeout: int) -> list[TelegramUpdate]:
        """Signal polling and block."""
        self.polled.set()
        await self._block.wait()
        raise AssertionError("unreachable")

    async def acknowledge_callback(self, callback_id: str) -> None:
        """Reject unexpected callback acknowledgement."""
        raise AssertionError(callback_id)

    async def send_message(self, text: str) -> None:
        """Capture a delivered notification."""
        self.messages.append(text)
        self.message_sent.set()


def test_retry_delays_are_1_2_4_8_16_then_30_forever() -> None:
    assert list(itertools.islice(retry_delays(), 8)) == [1, 2, 4, 8, 16, 30, 30, 30]


def test_service_injects_validated_transition_thresholds(tmp_path: Path) -> None:
    """Settings overrides must control the service engine instead of being ignored."""
    settings = settings_for(tmp_path).model_copy(update={"all_clear_seconds": 2.0})
    service = AlarmService(settings, BlockingRuView(), BlockingTelegram())
    service._engine.command(AlarmAction.ARM)
    service._engine.observe(SensorSample(healthy_esp32=True, presence=False, tick=1), 0.0)
    service._engine.observe(SensorSample(healthy_esp32=True, presence=True, tick=2), 1.0)
    service._engine.observe(SensorSample(healthy_esp32=True, presence=False, tick=3), 2.0)

    events = service._engine.observe(
        SensorSample(healthy_esp32=True, presence=False, tick=4), 4.0
    )

    assert [event.text for event in events] == ["All clear after continuous absence."]


@pytest.mark.parametrize(("armed", "text"), [(True, "Alarm restored: armed"), (False, "Alarm restored: disarmed")])
async def test_service_announces_restored_startup_state(
    tmp_path: Path, armed: bool, text: str
) -> None:
    """Startup must explicitly report the durable arm state before normal operation."""
    telegram = BlockingTelegram()
    service = AlarmService(
        settings_for(tmp_path),
        BlockingRuView(),
        telegram,
        load_state_fn=lambda path: PersistedState(armed=armed, telegram_offset=7),
    )

    task = asyncio.create_task(service.run())
    await asyncio.wait_for(telegram.message_sent.wait(), timeout=1.0)
    await cancel(task)

    assert telegram.messages[0] == text


class UpdateTelegram(BlockingTelegram):
    """Return one update batch and record durable side-effect ordering."""

    def __init__(self, updates: list[TelegramUpdate], order: list[str]) -> None:
        super().__init__()
        self._updates = updates
        self._returned = False
        self._order = order
        self.batch_processed = asyncio.Event()

    async def get_updates(self, offset: int, timeout: int) -> list[TelegramUpdate]:
        """Return the configured batch once, then block."""
        if not self._returned:
            self._returned = True
            return self._updates
        await self._block.wait()
        raise AssertionError("unreachable")

    async def acknowledge_callback(self, callback_id: str) -> None:
        """Record callback durability ordering."""
        self._order.append(f"ack:{callback_id}")

    async def send_message(self, text: str) -> None:
        """Record deliveries and signal after the command response."""
        self.messages.append(text)
        self._order.append(f"send:{text}")
        if len(self.messages) >= 2:
            self.batch_processed.set()


async def test_authorized_update_is_saved_before_callback_and_notification(tmp_path: Path) -> None:
    """A callback may be acknowledged and reported only after its new state is durable."""
    order: list[str] = []
    saved: list[PersistedState] = []
    telegram = UpdateTelegram(
        [
            TelegramUpdate(
                update_id=40,
                chat_id=123,
                action=AlarmAction.ARM,
                callback_id="callback-40",
            )
        ],
        order,
    )

    def save(path: Path, state: PersistedState) -> None:
        saved.append(state)
        order.append("save")

    service = AlarmService(
        settings_for(tmp_path),
        BlockingRuView(),
        telegram,
        load_state_fn=lambda path: PersistedState(telegram_offset=40),
        save_state_fn=save,
    )

    task = asyncio.create_task(service.run())
    await asyncio.wait_for(telegram.batch_processed.wait(), timeout=1.0)
    await cancel(task)

    assert saved == [PersistedState(armed=True, telegram_offset=41)]
    assert order.index("save") < order.index("ack:callback-40")
    assert order.index("ack:callback-40") < order.index("send:Alarm is armed.")


async def test_every_update_advances_durable_offset_even_when_inert(tmp_path: Path) -> None:
    """Unauthorized and unknown updates must never be replayed after restart."""
    saved: list[PersistedState] = []
    all_saved = asyncio.Event()
    telegram = UpdateTelegram(
        [
            TelegramUpdate(update_id=10, chat_id=999),
            TelegramUpdate(update_id=11, chat_id=123),
            TelegramUpdate(update_id=12),
        ],
        [],
    )

    def save(path: Path, state: PersistedState) -> None:
        saved.append(state)
        if len(saved) == 3:
            all_saved.set()

    service = AlarmService(
        settings_for(tmp_path),
        BlockingRuView(),
        telegram,
        load_state_fn=lambda path: PersistedState(telegram_offset=10),
        save_state_fn=save,
    )

    task = asyncio.create_task(service.run())
    await asyncio.wait_for(all_saved.wait(), timeout=1.0)
    await cancel(task)

    assert [state.telegram_offset for state in saved] == [11, 12, 13]
    assert all(not state.armed for state in saved)


async def test_out_of_order_consumed_update_cannot_regress_state_or_offset(tmp_path: Path) -> None:
    """A descending update ID must not replay its action or move the durable offset backward."""
    saved: list[PersistedState] = []
    service = AlarmService(
        settings_for(tmp_path),
        BlockingRuView(),
        BlockingTelegram(),
        save_state_fn=lambda path, state: saved.append(state),
    )
    service._offset = 12

    await service._apply_update(
        TelegramUpdate(update_id=12, chat_id=123, action=AlarmAction.ARM)
    )
    await service._apply_update(
        TelegramUpdate(update_id=10, chat_id=123, action=AlarmAction.DISARM)
    )

    assert saved == [PersistedState(armed=True, telegram_offset=13)]
    assert service._engine.snapshot(service._offset) == PersistedState(
        armed=True, telegram_offset=13
    )


class RetryingTelegram(UpdateTelegram):
    """Fail one startup delivery without disrupting polling or state."""

    def __init__(self, order: list[str]) -> None:
        super().__init__([TelegramUpdate(update_id=4, chat_id=123, action=AlarmAction.ARM)], order)
        self.attempts: list[str] = []
        self.retried = asyncio.Event()

    async def send_message(self, text: str) -> None:
        """Fail the first attempt and accept subsequent messages."""
        self.attempts.append(text)
        if len(self.attempts) == 1:
            raise TelegramError("sendMessage")
        await super().send_message(text)
        if len(self.attempts) >= 3:
            self.retried.set()


async def test_delivery_retry_isolated_from_durable_state_and_sensing(tmp_path: Path) -> None:
    """A send failure must retry in place without rolling back or blocking other workers."""
    sleeps: list[float] = []
    saved: list[PersistedState] = []
    order: list[str] = []
    telegram = RetryingTelegram(order)
    ruv_client = BlockingRuView()

    async def yielding_sleep(delay: float) -> None:
        sleeps.append(delay)
        await asyncio.sleep(0)

    service = AlarmService(
        settings_for(tmp_path),
        ruv_client,
        telegram,
        load_state_fn=lambda path: PersistedState(telegram_offset=4),
        save_state_fn=lambda path, state: saved.append(state),
        sleep=yielding_sleep,
    )

    task = asyncio.create_task(service.run())
    await asyncio.wait_for(telegram.retried.wait(), timeout=1.0)
    await asyncio.wait_for(ruv_client.sampled.wait(), timeout=1.0)
    await cancel(task)

    assert telegram.attempts[:2] == ["Alarm restored: disarmed", "Alarm restored: disarmed"]
    assert saved == [PersistedState(armed=True, telegram_offset=5)]
    assert 1 in sleeps


class RecoveringRuView:
    """Raise once, then prove sensing retries independently."""

    def __init__(self) -> None:
        self.calls = 0
        self.retried = asyncio.Event()
        self._block = asyncio.Event()

    async def sample(self) -> SensorSample:
        """Fail the first sample and block after the retry."""
        self.calls += 1
        if self.calls == 1:
            raise RuViewError("health")
        self.retried.set()
        await self._block.wait()
        raise AssertionError("unreachable")


async def test_ruview_outage_retries_without_rewriting_state_or_stopping_telegram(
    tmp_path: Path,
) -> None:
    """A transient sensing outage must stay inside sensing supervision."""
    sleeps: list[float] = []
    saved: list[PersistedState] = []
    ruv_client = RecoveringRuView()
    telegram = UpdateTelegram([TelegramUpdate(update_id=8, chat_id=999)], [])

    async def yielding_sleep(delay: float) -> None:
        sleeps.append(delay)
        await asyncio.sleep(0)

    service = AlarmService(
        settings_for(tmp_path),
        ruv_client,
        telegram,
        load_state_fn=lambda path: PersistedState(armed=True, telegram_offset=8),
        save_state_fn=lambda path, state: saved.append(state),
        sleep=yielding_sleep,
    )

    task = asyncio.create_task(service.run())
    await asyncio.wait_for(ruv_client.retried.wait(), timeout=1.0)
    while not saved:
        await asyncio.sleep(0)
    await cancel(task)

    assert sleeps[0] == 1
    assert saved == [PersistedState(armed=True, telegram_offset=9)]


class RecoveringTelegram(BlockingTelegram):
    """Fail polling once, then return a durable command."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.returned = asyncio.Event()

    async def get_updates(self, offset: int, timeout: int) -> list[TelegramUpdate]:
        """Fail the first poll and return one command on retry."""
        self.calls += 1
        if self.calls == 1:
            raise TelegramError("getUpdates")
        if self.calls == 2:
            self.returned.set()
            return [TelegramUpdate(update_id=20, chat_id=123, action=AlarmAction.ARM)]
        await self._block.wait()
        raise AssertionError("unreachable")


async def test_telegram_outage_retries_without_stopping_sensing(tmp_path: Path) -> None:
    """A transient long-poll outage must stay inside Telegram supervision."""
    sleeps: list[float] = []
    saved = asyncio.Event()
    telegram = RecoveringTelegram()
    ruv_client = BlockingRuView()

    async def yielding_sleep(delay: float) -> None:
        sleeps.append(delay)
        await asyncio.sleep(0)

    service = AlarmService(
        settings_for(tmp_path),
        ruv_client,
        telegram,
        save_state_fn=lambda path, state: saved.set(),
        sleep=yielding_sleep,
    )

    task = asyncio.create_task(service.run())
    await asyncio.wait_for(telegram.returned.wait(), timeout=1.0)
    await asyncio.wait_for(saved.wait(), timeout=1.0)
    await asyncio.wait_for(ruv_client.sampled.wait(), timeout=1.0)
    await cancel(task)

    assert sleeps[0] == 1


async def test_failed_callback_ack_is_bounded_and_does_not_wedge_later_updates(
    tmp_path: Path,
) -> None:
    """An expired callback must not block command notifications or polling progress."""
    attempts: list[str] = []
    saved: list[PersistedState] = []

    class InvalidCallbackTelegram(BlockingTelegram):
        async def acknowledge_callback(self, callback_id: str) -> None:
            attempts.append(callback_id)
            raise TelegramError("answerCallbackQuery", status_code=400)

    async def unexpected_sleep(delay: float) -> None:
        pytest.fail(f"callback acknowledgement retried after {delay}")

    telegram = InvalidCallbackTelegram()
    service = AlarmService(
        settings_for(tmp_path),
        BlockingRuView(),
        telegram,
        save_state_fn=lambda path, state: saved.append(state),
        sleep=unexpected_sleep,
        utc_now=lambda: 99.0,
    )
    service._heartbeats = {"telegram": 17.0}

    await service._apply_update(
        TelegramUpdate(
            update_id=1,
            chat_id=123,
            action=AlarmAction.ARM,
            callback_id="expired-1",
        )
    )
    await service._apply_update(
        TelegramUpdate(update_id=2, chat_id=123, action=AlarmAction.STATUS)
    )

    queued = [service._notifications.get_nowait(), service._notifications.get_nowait()]

    assert attempts == ["expired-1"]
    assert [state.telegram_offset for state in saved] == [2, 3]
    assert queued == ["Alarm is armed.", "Alarm is armed."]
    assert service._heartbeats["telegram"] == 17.0


async def test_unexpected_worker_return_terminates_the_service(tmp_path: Path) -> None:
    """A normally returning child must fail supervision and cancel its siblings."""
    service = AlarmService(settings_for(tmp_path), BlockingRuView(), BlockingTelegram())

    async def returns_unexpectedly() -> None:
        return

    service._sensing_loop = returns_unexpectedly  # type: ignore[method-assign]

    with pytest.raises(ExceptionGroup) as error:
        await asyncio.wait_for(service.run(), timeout=1.0)

    assert "sensing loop exited unexpectedly" in repr(error.value)


async def test_unexpected_worker_failure_terminates_the_service(tmp_path: Path) -> None:
    """An unclassified worker exception must fail supervision and cancel siblings."""
    class BrokenRuView:
        async def sample(self) -> SensorSample:
            raise RuntimeError("broken invariant")

    service = AlarmService(settings_for(tmp_path), BrokenRuView(), BlockingTelegram())

    with pytest.raises(ExceptionGroup) as error:
        await asyncio.wait_for(service.run(), timeout=1.0)

    assert "broken invariant" in repr(error.value)


async def test_watchdog_writes_complete_loop_heartbeat_snapshot(tmp_path: Path) -> None:
    """The watchdog publication must name every supervised loop and main."""
    snapshots: list[dict[str, float]] = []
    published = asyncio.Event()
    block = asyncio.Event()

    def capture(path: Path, snapshot: dict[str, float]) -> None:
        snapshots.append(dict(snapshot))
        published.set()

    async def watchdog_sleep(delay: float) -> None:
        await block.wait()

    service = AlarmService(
        settings_for(tmp_path),
        BlockingRuView(),
        BlockingTelegram(),
        heartbeat_writer=capture,
        sleep=watchdog_sleep,
        utc_now=lambda: 1_000.0,
    )

    task = asyncio.create_task(service.run())
    await asyncio.wait_for(published.wait(), timeout=1.0)
    await cancel(task)

    assert set(snapshots[0]) == {"main", "sensing", "telegram", "notifications"}
    assert snapshots[0]["main"] == 1_000.0


async def test_watchdog_stale_worker_terminates_taskgroup_and_cancels_siblings(
    tmp_path: Path,
) -> None:
    """A stale worker heartbeat must fail supervision and cancel blocked peer loops."""
    now = 1_000.0
    ruv_client = BlockingRuView()
    telegram = BlockingTelegram()

    async def advancing_watchdog_sleep(delay: float) -> None:
        nonlocal now
        if delay == 10.0:
            now += 46.0
        await asyncio.sleep(0)

    service = AlarmService(
        settings_for(tmp_path),
        ruv_client,
        telegram,
        heartbeat_writer=lambda path, snapshot: None,
        sleep=advancing_watchdog_sleep,
        utc_now=lambda: now,
    )

    with pytest.raises(ExceptionGroup) as error:
        await asyncio.wait_for(service.run(), timeout=1.0)

    assert "sensing loop heartbeat stale" in repr(error.value)
    assert ruv_client.sampled.is_set()
    assert telegram.polled.is_set()


async def test_ruview_attempts_use_full_backoff_while_offline_timing_is_observed(
    tmp_path: Path,
) -> None:
    """HTTP attempts keep exact backoff while offline detection advances independently."""
    now = 0.0
    attempt_times: list[float] = []

    class FailedRuView:
        def __init__(self) -> None:
            self.sixth_attempt = asyncio.Event()
            self.block = asyncio.Event()

        async def sample(self) -> SensorSample:
            attempt_times.append(now)
            if len(attempt_times) == 6:
                self.sixth_attempt.set()
                await self.block.wait()
            raise RuViewError("health")

    async def advancing_sleep(delay: float) -> None:
        nonlocal now
        now += delay
        await asyncio.sleep(0)

    ruv_client = FailedRuView()
    service = AlarmService(
        settings_for(tmp_path),
        ruv_client,
        BlockingTelegram(),
        sleep=advancing_sleep,
        utc_now=lambda: now,
        monotonic_now=lambda: now,
    )

    task = asyncio.create_task(service._sensing_loop())
    await asyncio.wait_for(ruv_client.sixth_attempt.wait(), timeout=1.0)
    await cancel(task)

    assert attempt_times == [0.0, 1.0, 3.0, 7.0, 15.0, 31.0]
    assert service._notifications.get_nowait() == "Sensor is offline."


async def test_taskgroup_failure_cancels_siblings_and_closes_both_remote_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fatal worker must cancel real TaskGroup peers before both pools close."""
    clients: list[object] = []
    polling = asyncio.Event()
    delivering = asyncio.Event()
    poll_cancelled = asyncio.Event()
    delivery_cancelled = asyncio.Event()
    block = asyncio.Event()

    class FakeHttpClient:
        def __init__(self, *, timeout: httpx.Timeout) -> None:
            self.timeout = timeout
            self.closed = False
            clients.append(self)

        async def __aenter__(self) -> "FakeHttpClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            self.closed = True

    class FatalRuView:
        async def sample(self) -> SensorSample:
            await polling.wait()
            await delivering.wait()
            raise RuntimeError("fatal sensing invariant")

    class CancelledTelegram:
        async def get_updates(self, offset: int, timeout: int) -> list[TelegramUpdate]:
            polling.set()
            try:
                await block.wait()
            except asyncio.CancelledError:
                poll_cancelled.set()
                raise
            raise AssertionError("unreachable")

        async def acknowledge_callback(self, callback_id: str) -> None:
            raise AssertionError(callback_id)

        async def send_message(self, text: str) -> None:
            delivering.set()
            try:
                await block.wait()
            except asyncio.CancelledError:
                delivery_cancelled.set()
                raise

    monkeypatch.setattr("ruview_alarm.service.httpx.AsyncClient", FakeHttpClient)
    monkeypatch.setattr("ruview_alarm.service.RuViewClient", lambda *args: FatalRuView())
    monkeypatch.setattr("ruview_alarm.service.TelegramClient", lambda *args: CancelledTelegram())

    with pytest.raises(ExceptionGroup) as error:
        await asyncio.wait_for(run_alarm(settings_for(tmp_path)), timeout=1.0)

    assert "fatal sensing invariant" in repr(error.value)
    assert poll_cancelled.is_set()
    assert delivery_cancelled.is_set()
    assert len(clients) == 2
    assert all(client.closed for client in clients)
    assert all(client.timeout.connect is not None for client in clients)
    assert all(client.timeout.read is not None for client in clients)
    assert all(client.timeout.write is not None for client in clients)
    assert all(client.timeout.pool is not None for client in clients)


def test_process_entry_uses_utc_logging_and_redacts_fatal_exception_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A fatal exception must exit nonzero without rendering its secret-bearing value."""
    sentinel = "DO_NOT_LOG_THIS_SECRET"

    class InvalidSettings:
        def __init__(self) -> None:
            raise RuntimeError(sentinel)

    monkeypatch.setattr(process_entry, "Settings", InvalidSettings)

    with caplog.at_level("ERROR"):
        exit_code = process_entry.main()

    assert exit_code == 1
    assert sentinel not in caplog.text
    assert logging.Formatter.converter is time.gmtime


def test_process_logging_silences_http_client_token_bearing_info_records(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HTTP request INFO records must not expose Telegram's tokenized URL."""
    sentinel = "DO_NOT_LOG_TELEGRAM_TOKEN"
    process_entry._configure_logging()

    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info(
            "HTTP Request: GET https://api.telegram.org/bot%s/getUpdates", sentinel
        )
        logging.getLogger("httpcore.connection").info(
            "connect_tcp to bot%s", sentinel
        )

    assert sentinel not in caplog.text
