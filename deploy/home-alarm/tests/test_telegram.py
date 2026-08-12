"""Tests for authorized, secret-safe Telegram Bot API control."""

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from ruview_alarm.models import AlarmAction, TelegramUpdate
from ruview_alarm.telegram import TelegramClient, TelegramError


def client_for(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[TelegramClient, httpx.AsyncClient]:
    """Build the adapter against an in-memory Telegram API."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        TelegramClient(
            client=client,
            base_url="https://telegram.test",
            bot_token=SecretStr("test-telegram-token"),
            allowed_chat_id=123,
        ),
        client,
    )


async def test_get_updates_recognizes_authorized_text_command_and_poll_parameters() -> None:
    """A valid configured-chat command must retain its ID and requested poll parameters."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"ok": True, "result": [{"update_id": 41, "message": {"chat": {"id": 123}, "text": "/arm@alarmbot"}}]},
        )

    telegram, client = client_for(handler)
    try:
        updates = await telegram.get_updates(offset=41, timeout=20)
    finally:
        await client.aclose()

    assert updates == [TelegramUpdate(update_id=41, chat_id=123, action=AlarmAction.ARM)]
    assert captured[0].url.params["offset"] == "41"
    assert captured[0].url.params["timeout"] == "20"


@pytest.mark.parametrize(
    ("text", "action"),
    [("/disarm", AlarmAction.DISARM), ("/status@alarmbot", AlarmAction.STATUS)],
)
async def test_get_updates_recognizes_authorized_text_actions(text: str, action: AlarmAction) -> None:
    """Each supported configured-chat text action must map to its alarm action."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True, "result": [{"update_id": 42, "message": {"chat": {"id": 123}, "text": text}}]},
        )

    telegram, client = client_for(handler)
    try:
        updates = await telegram.get_updates(offset=42, timeout=20)
    finally:
        await client.aclose()

    assert updates == [TelegramUpdate(update_id=42, chat_id=123, action=action)]


async def test_get_updates_recognizes_authorized_callback_and_preserves_callback_id() -> None:
    """A configured-chat callback must become an action the service can acknowledge."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 43,
                        "callback_query": {
                            "id": "callback-43",
                            "data": "disarm",
                            "message": {"chat": {"id": 123}},
                        },
                    }
                ],
            },
        )

    telegram, client = client_for(handler)
    try:
        updates = await telegram.get_updates(offset=43, timeout=20)
    finally:
        await client.aclose()

    assert updates == [
        TelegramUpdate(
            update_id=43,
            chat_id=123,
            action=AlarmAction.DISARM,
            callback_id="callback-43",
        )
    ]


async def test_get_updates_preserves_unauthorized_update_id_without_action() -> None:
    """An unauthorized update must advance the durable offset without controlling the alarm."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True, "result": [{"update_id": 44, "message": {"chat": {"id": 999}, "text": "/arm"}}]},
        )

    telegram, client = client_for(handler)
    try:
        updates = await telegram.get_updates(offset=44, timeout=20)
    finally:
        await client.aclose()

    assert updates == [TelegramUpdate(update_id=44, chat_id=999)]


async def test_get_updates_preserves_unknown_and_non_message_update_ids_without_actions() -> None:
    """Unknown or non-command updates must remain offset-advancing inert records."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {"update_id": 45, "message": {"chat": {"id": 123}, "text": "/unknown"}},
                    {"update_id": 46, "edited_message": {"chat": {"id": 123}, "text": "/arm"}},
                ],
            },
        )

    telegram, client = client_for(handler)
    try:
        updates = await telegram.get_updates(offset=45, timeout=20)
    finally:
        await client.aclose()

    assert updates == [TelegramUpdate(update_id=45, chat_id=123), TelegramUpdate(update_id=46)]


async def test_acknowledge_callback_posts_the_callback_id() -> None:
    """Acknowledgement must send exactly the callback identifier to Telegram."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    telegram, client = client_for(handler)
    try:
        await telegram.acknowledge_callback("callback-47")
    finally:
        await client.aclose()

    assert captured[0].url.path.endswith("/answerCallbackQuery")
    assert json.loads(captured[0].content) == {"callback_query_id": "callback-47"}


async def test_send_message_targets_configured_chat_with_control_keyboard() -> None:
    """Notifications must go only to the configured chat with all three control buttons."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 48}})

    telegram, client = client_for(handler)
    try:
        await telegram.send_message("Alarm is armed.")
    finally:
        await client.aclose()

    assert captured[0].url.path.endswith("/sendMessage")
    assert json.loads(captured[0].content) == {
        "chat_id": 123,
        "text": "Alarm is armed.",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Arm", "callback_data": "arm"},
                    {"text": "Disarm", "callback_data": "disarm"},
                    {"text": "Status", "callback_data": "status"},
                ]
            ]
        },
    }


async def test_bot_api_errors_expose_only_operation_and_status() -> None:
    """Bot API failures must not retain tokenized request details in public errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"ok": False, "description": "forbidden"})

    telegram, client = client_for(handler)
    try:
        with pytest.raises(TelegramError) as error:
            await telegram.send_message("Alarm is armed.")
    finally:
        await client.aclose()

    assert error.value.operation == "sendMessage"
    assert error.value.status_code == 403
    assert "telegram.test" not in str(error.value)
    assert "test-telegram-token" not in str(error.value)


async def test_bot_api_error_envelope_exposes_only_operation_and_status() -> None:
    """A successful HTTP response with a failed Bot API envelope must stay redacted."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "forbidden"})

    telegram, client = client_for(handler)
    try:
        with pytest.raises(TelegramError) as error:
            await telegram.send_message("Alarm is armed.")
    finally:
        await client.aclose()

    assert error.value.operation == "sendMessage"
    assert error.value.status_code == 200
    assert "telegram.test" not in str(error.value)
    assert "test-telegram-token" not in str(error.value)


async def test_transport_errors_expose_only_operation_and_no_token() -> None:
    """Transport exceptions must be redacted instead of surfacing their request URL."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("https://telegram.test/bottest-telegram-token/getUpdates", request=request)

    telegram, client = client_for(handler)
    try:
        with pytest.raises(TelegramError) as error:
            await telegram.get_updates(offset=49, timeout=20)
    finally:
        await client.aclose()

    assert error.value.operation == "getUpdates"
    assert error.value.status_code is None
    assert "telegram.test" not in str(error.value)
    assert "test-telegram-token" not in str(error.value)
