"""Hermetic asyncio HTTP endpoints and service orchestration for integration tests."""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import SecretStr

from ruview_alarm.config import Settings
from ruview_alarm.ruview import RuViewClient
from ruview_alarm.service import AlarmService
from ruview_alarm.telegram import TelegramClient

_MAX_REQUEST_BYTES = 1_048_576


@dataclass(frozen=True)
class _Request:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes

    def json(self) -> object:
        """Decode the request body as JSON."""
        return json.loads(self.body)


class _AsyncJsonServer:
    """Minimal one-request-per-connection JSON server bound to loopback."""

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._handlers: set[asyncio.Task[None]] = set()
        self.base_url = ""

    async def __aenter__(self) -> "_AsyncJsonServer":
        self._server = await asyncio.start_server(self._handle_connection, "127.0.0.1", 0)
        socket = self._server.sockets[0]
        port = int(socket.getsockname()[1])
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for writer in tuple(self._writers):
            writer.close()
        for writer in tuple(self._writers):
            with suppress(OSError):
                await writer.wait_closed()
        if self._handlers:
            await asyncio.gather(*tuple(self._handlers), return_exceptions=True)
        assert not [task for task in self._handlers if not task.done()]

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._handlers.add(task)
        self._writers.add(writer)
        try:
            request = await self._read_request(reader)
            status, payload = await self._dispatch(request)
            await self._write_response(writer, status, payload)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except (UnicodeError, ValueError, json.JSONDecodeError):
            await self._write_response(writer, 400, {"error": "bad request"})
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
            self._writers.discard(writer)
            self._handlers.discard(task)

    async def _read_request(self, reader: asyncio.StreamReader) -> _Request:
        header_bytes = await reader.readuntil(b"\r\n\r\n")
        if len(header_bytes) > _MAX_REQUEST_BYTES:
            raise ValueError("headers too large")
        lines = header_bytes.decode("iso-8859-1").split("\r\n")
        method, target, protocol = lines[0].split()
        if protocol not in {"HTTP/1.0", "HTTP/1.1"}:
            raise ValueError("unsupported protocol")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                continue
            name, value = line.split(":", maxsplit=1)
            headers[name.lower()] = value.strip()
        content_length = int(headers.get("content-length", "0"))
        if content_length < 0 or content_length > _MAX_REQUEST_BYTES:
            raise ValueError("body too large")
        body = await reader.readexactly(content_length)
        split = urlsplit(target)
        return _Request(method, split.path, parse_qs(split.query), headers, body)

    @staticmethod
    async def _write_response(writer: asyncio.StreamWriter, status: int, payload: object) -> None:
        reason = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            503: "Unavailable",
        }[status]
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        writer.write(
            (
                f"HTTP/1.1 {status} {reason}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            + body
        )
        await writer.drain()

    async def _dispatch(self, request: _Request) -> tuple[int, object]:
        raise NotImplementedError


class FakeRuView(_AsyncJsonServer):
    """Authenticated RuView health/latest endpoint with explicit state controls."""

    def __init__(self, api_token: str) -> None:
        super().__init__()
        self._authorization = f"Bearer {api_token}"
        self._health: dict[str, object] = {
            "status": "ok",
            "source": "esp32",
            "tick": 0,
            "clients": 1,
        }
        self._latest: dict[str, object] = {
            "source": "esp32",
            "tick": 0,
            "classification": {"presence": False},
        }

    def set_healthy_sample(self, *, presence: bool, tick: int) -> None:
        """Publish one internally consistent healthy ESP32 observation."""
        self._health = {"status": "ok", "source": "esp32", "tick": tick, "clients": 1}
        self._latest = {
            "source": "esp32",
            "tick": tick,
            "classification": {"presence": presence},
        }

    def set_unhealthy(self) -> None:
        """Publish a degraded ESP32 health response."""
        self._health = {"status": "degraded", "source": "esp32", "tick": 0, "clients": 0}

    async def _dispatch(self, request: _Request) -> tuple[int, object]:
        if request.headers.get("authorization") != self._authorization:
            return 401, {"error": "unauthorized"}
        if request.method != "GET":
            return 404, {"error": "not found"}
        if request.path == "/health":
            return 200, self._health
        if request.path == "/api/v1/sensing/latest":
            return 200, self._latest
        return 404, {"error": "not found"}


class FakeTelegram(_AsyncJsonServer):
    """Bot API-compatible endpoint recording externally observable behavior."""

    def __init__(self, bot_token: str) -> None:
        super().__init__()
        self._route_prefix = f"/bot{bot_token}/"
        self._updates: list[dict[str, object]] = []
        self._updates_available = asyncio.Event()
        self._message_failures = 0
        self.message_attempts: list[str] = []
        self.message_texts: list[str] = []
        self.acknowledgements: list[str] = []

    def queue_message(self, *, update_id: int, chat_id: int, text: str) -> None:
        """Queue one Telegram message update."""
        self._updates.append(
            {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}}
        )
        self._updates_available.set()

    def queue_callback(
        self,
        *,
        update_id: int,
        chat_id: int,
        callback_id: str,
        action: str,
    ) -> None:
        """Queue one Telegram callback update."""
        self._updates.append(
            {
                "update_id": update_id,
                "callback_query": {
                    "id": callback_id,
                    "data": action,
                    "message": {"chat": {"id": chat_id}},
                },
            }
        )
        self._updates_available.set()

    def fail_next_messages(self, count: int) -> None:
        """Return retryable failures for the next outbound messages."""
        self._message_failures = count

    async def _dispatch(self, request: _Request) -> tuple[int, object]:
        if not request.path.startswith(self._route_prefix):
            return 401, {"ok": False, "result": False}
        method = request.path.removeprefix(self._route_prefix)
        if request.method == "GET" and method == "getUpdates":
            offset = int(request.query.get("offset", ["0"])[0])
            updates = [item for item in self._updates if int(item["update_id"]) >= offset]
            if not updates:
                self._updates_available.clear()
                updates = [item for item in self._updates if int(item["update_id"]) >= offset]
                if not updates:
                    with suppress(TimeoutError):
                        await asyncio.wait_for(self._updates_available.wait(), timeout=0.02)
                    updates = [item for item in self._updates if int(item["update_id"]) >= offset]
            return 200, {"ok": True, "result": updates}
        if request.method != "POST":
            return 404, {"ok": False, "result": False}
        payload = request.json()
        if not isinstance(payload, dict):
            return 400, {"ok": False, "result": False}
        if method == "sendMessage":
            text = payload.get("text")
            if not isinstance(text, str):
                return 400, {"ok": False, "result": False}
            self.message_attempts.append(text)
            if self._message_failures:
                self._message_failures -= 1
                return 503, {"ok": False, "result": False}
            self.message_texts.append(text)
            return 200, {"ok": True, "result": {"message_id": len(self.message_texts)}}
        if method == "answerCallbackQuery":
            callback_id = payload.get("callback_query_id")
            if not isinstance(callback_id, str):
                return 400, {"ok": False, "result": False}
            self.acknowledgements.append(callback_id)
            return 200, {"ok": True, "result": True}
        return 404, {"ok": False, "result": False}


class _StepClock:
    def __init__(self, step: float) -> None:
        self._value = 0.0
        self._step = step

    def __call__(self) -> float:
        value = self._value
        self._value += self._step
        return value


@dataclass
class IntegrationHarness:
    """Resources exposed to one running service integration scenario."""

    settings: Settings
    ruview: FakeRuView
    telegram: FakeTelegram
    ruview_http: httpx.AsyncClient
    telegram_http: httpx.AsyncClient


@asynccontextmanager
async def integration_harness(
    tmp_path: Path, *, monotonic_step: float = 1.0
) -> AsyncIterator[IntegrationHarness]:
    """Run the real service/adapters against hermetic HTTP endpoints."""
    telegram_token = "integration-telegram-token"
    ruview_token = "integration-ruview-token"
    async with AsyncExitStack() as stack:
        ruview = await stack.enter_async_context(FakeRuView(ruview_token))
        telegram = await stack.enter_async_context(FakeTelegram(telegram_token))
        ruview_http = await stack.enter_async_context(httpx.AsyncClient(timeout=1.0))
        telegram_http = await stack.enter_async_context(httpx.AsyncClient(timeout=1.0))
        settings = Settings(
            telegram_bot_token=telegram_token,
            telegram_chat_id=123,
            ruview_api_token=ruview_token,
            ruview_base_url=ruview.base_url,
            telegram_base_url=telegram.base_url,
            state_path=tmp_path / "state.json",
            health_path=tmp_path / "health.json",
            poll_seconds=0.005,
            all_clear_seconds=0.02,
            offline_seconds=0.02,
            telegram_poll_seconds=1,
        )

        async def quick_sleep(delay: float) -> None:
            await asyncio.sleep(0.05 if delay >= 10.0 else 0.005)

        service = AlarmService(
            settings,
            RuViewClient(ruview_http, ruview.base_url, SecretStr(ruview_token)),
            TelegramClient(telegram_http, telegram.base_url, SecretStr(telegram_token), 123),
            sleep=quick_sleep,
            utc_now=time.time,
            monotonic_now=_StepClock(monotonic_step),
        )
        service_task = asyncio.create_task(service.run(), name="alarm-service-integration")
        harness = IntegrationHarness(
            settings,
            ruview,
            telegram,
            ruview_http,
            telegram_http,
        )
        try:
            yield harness
        finally:
            service_task.cancel()
            with suppress(asyncio.CancelledError):
                await service_task
            assert service_task.done()


async def wait_until(
    condition: Callable[[], bool], *, timeout: float = 2.0, interval: float = 0.005
) -> None:
    """Wait for an observable integration result without fixed test sleeps."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(interval)
