"""Supervised alarm orchestration with durable commands and isolated retries."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Protocol

import httpx

from ruview_alarm.alarm import AlarmEngine
from ruview_alarm.config import Settings
from ruview_alarm.healthcheck import write_heartbeat
from ruview_alarm.models import AlarmEvent, PersistedState, SensorSample, TelegramUpdate
from ruview_alarm.ruview import RuViewClient, RuViewError
from ruview_alarm.state import load_state, save_state
from ruview_alarm.telegram import TelegramClient, TelegramError

Sleep = Callable[[float], Awaitable[None]]
HeartbeatWriter = Callable[[Path, dict[str, float]], None]

_WORKER_MAX_AGES = {"sensing": 45.0, "telegram": 60.0, "notifications": 45.0}


class RuViewAdapter(Protocol):
    """Sensing behavior consumed by the service."""

    async def sample(self) -> SensorSample:
        """Return one validated sensing sample."""


class TelegramAdapter(Protocol):
    """Telegram behavior consumed by the service."""

    async def get_updates(self, offset: int, timeout: int) -> list[TelegramUpdate]:
        """Return normalized updates at or beyond an offset."""

    async def acknowledge_callback(self, callback_id: str) -> None:
        """Acknowledge one authorized callback."""

    async def send_message(self, text: str) -> None:
        """Deliver one alarm message."""


def retry_delays() -> Iterator[float]:
    """Yield bounded exponential retry delays forever."""
    delay = 1.0
    while True:
        yield delay
        delay = min(delay * 2, 30.0)


class AlarmService:
    """Run alarm state, remote adapters, delivery, and health as one unit."""

    def __init__(
        self,
        settings: Settings,
        ruv_client: RuViewAdapter,
        telegram: TelegramAdapter,
        *,
        load_state_fn: Callable[[Path], PersistedState] = load_state,
        save_state_fn: Callable[[Path, PersistedState], None] = save_state,
        heartbeat_writer: HeartbeatWriter = write_heartbeat,
        sleep: Sleep = asyncio.sleep,
        utc_now: Callable[[], float] = time.time,
        monotonic_now: Callable[[], float] | None = None,
    ) -> None:
        """Create a service with injectable side-effect boundaries."""
        self._settings = settings
        self._ruview = ruv_client
        self._telegram = telegram
        self._load_state = load_state_fn
        self._save_state = save_state_fn
        self._write_heartbeat = heartbeat_writer
        self._sleep = sleep
        self._utc_now = utc_now
        self._monotonic_now = monotonic_now
        self._engine = AlarmEngine()
        self._notifications: asyncio.Queue[str] = asyncio.Queue()
        self._heartbeats: dict[str, float] = {}
        self._offset = 0

    async def run(self) -> None:
        """Restore durable state and supervise all four workers."""
        state = self._load_state(self._settings.state_path)
        self._engine.restore(state)
        self._offset = state.telegram_offset or 0
        restored = "armed" if state.armed else "disarmed"
        self._notifications.put_nowait(f"Alarm restored: {restored}")

        started_at = self._utc_now()
        self._heartbeats = {
            "main": started_at,
            "sensing": started_at,
            "telegram": started_at,
            "notifications": started_at,
        }
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._supervise("sensing", self._sensing_loop))
            tasks.create_task(self._supervise("telegram", self._telegram_loop))
            tasks.create_task(self._supervise("notifications", self._notification_loop))
            tasks.create_task(self._supervise("watchdog", self._watchdog_loop))

    async def _supervise(self, name: str, worker: Callable[[], Awaitable[None]]) -> None:
        """Turn an unexpected normal worker return into a process-fatal failure."""
        await worker()
        raise RuntimeError(f"{name} loop exited unexpectedly")

    async def _sensing_loop(self) -> None:
        delays = retry_delays()
        loop = asyncio.get_running_loop()
        monotonic_now = self._monotonic_now or loop.time
        while True:
            self._mark_live("sensing")
            try:
                sample = await self._ruview.sample()
            except RuViewError:
                self._queue_events(
                    self._engine.observe(SensorSample(healthy_esp32=False), monotonic_now())
                )
                self._mark_live("sensing")
                await self._sleep(min(next(delays), self._settings.poll_seconds))
                continue

            self._queue_events(self._engine.observe(sample, monotonic_now()))
            self._mark_live("sensing")
            delays = retry_delays()
            await self._sleep(self._settings.poll_seconds)

    async def _telegram_loop(self) -> None:
        delays = retry_delays()
        while True:
            self._mark_live("telegram")
            try:
                updates = await self._telegram.get_updates(
                    self._offset, self._settings.telegram_poll_seconds
                )
            except TelegramError:
                self._mark_live("telegram")
                await self._sleep(next(delays))
                continue

            delays = retry_delays()
            for update in updates:
                await self._apply_update(update)
                self._mark_live("telegram")

    async def _apply_update(self, update: TelegramUpdate) -> None:
        if update.update_id < self._offset:
            return
        next_offset = update.update_id + 1
        events = self._engine.command(update.action) if update.action is not None else []
        self._save_state(self._settings.state_path, self._engine.snapshot(next_offset))
        self._offset = next_offset

        if update.callback_id is not None:
            await self._acknowledge_with_retry(update.callback_id)
        self._queue_events(events)

    async def _acknowledge_with_retry(self, callback_id: str) -> None:
        delays = retry_delays()
        while True:
            self._mark_live("telegram")
            try:
                await self._telegram.acknowledge_callback(callback_id)
                return
            except TelegramError:
                self._mark_live("telegram")
                await self._sleep(next(delays))

    async def _notification_loop(self) -> None:
        while True:
            self._mark_live("notifications")
            try:
                async with asyncio.timeout(10.0):
                    text = await self._notifications.get()
            except TimeoutError:
                continue

            delays = retry_delays()
            while True:
                self._mark_live("notifications")
                try:
                    await self._telegram.send_message(text)
                except TelegramError:
                    self._mark_live("notifications")
                    await self._sleep(next(delays))
                    continue
                self._notifications.task_done()
                break

    async def _watchdog_loop(self) -> None:
        while True:
            now = self._utc_now()
            for name, maximum_age in _WORKER_MAX_AGES.items():
                if now - self._heartbeats[name] > maximum_age:
                    raise RuntimeError(f"{name} loop heartbeat stale")
            self._heartbeats["main"] = now
            self._write_heartbeat(self._settings.health_path, self._heartbeats)
            await self._sleep(10.0)

    def _mark_live(self, name: str) -> None:
        self._heartbeats[name] = self._utc_now()

    def _queue_events(self, events: list[AlarmEvent]) -> None:
        for event in events:
            self._notifications.put_nowait(event.text)


async def run_alarm(settings: Settings) -> None:
    """Build one bounded connection pool per remote and run the alarm service."""
    ruv_timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
    telegram_timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    async with (
        httpx.AsyncClient(timeout=ruv_timeout) as ruv_http,
        httpx.AsyncClient(timeout=telegram_timeout) as telegram_http,
    ):
        service = AlarmService(
            settings,
            RuViewClient(
                ruv_http,
                str(settings.ruview_base_url),
                settings.ruview_api_token,
            ),
            TelegramClient(
                telegram_http,
                str(settings.telegram_base_url),
                settings.telegram_bot_token,
                settings.telegram_chat_id,
            ),
        )
        await service.run()
