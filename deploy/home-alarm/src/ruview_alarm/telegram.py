"""Authorized, secret-safe Telegram Bot API control adapter."""

from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import SecretStr

from ruview_alarm.models import AlarmAction, TelegramUpdate


class TelegramError(Exception):
    """A redacted Telegram transport, protocol, or schema failure."""

    def __init__(self, operation: str, status_code: int | None = None) -> None:
        """Record only the operation and optional HTTP status metadata."""
        self.operation = operation
        self.status_code = status_code
        detail = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"Telegram {operation} request failed{detail}")


class TelegramClient:
    """Poll and send Telegram controls for one configured chat."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        bot_token: SecretStr,
        allowed_chat_id: int,
    ) -> None:
        """Create an adapter using the caller-owned HTTP client."""
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._bot_token = bot_token
        self._allowed_chat_id = allowed_chat_id

    async def get_updates(self, offset: int, timeout: int) -> list[TelegramUpdate]:
        """Poll updates, preserving every update ID regardless of authorization."""
        result = await self._call("getUpdates", {"offset": offset, "timeout": timeout})
        if not isinstance(result, list):
            raise TelegramError("getUpdates")
        return [self._parse_update(item) for item in result]

    async def acknowledge_callback(self, callback_id: str) -> None:
        """Dismiss an authorized callback's Telegram client progress indicator."""
        await self._call("answerCallbackQuery", {"callback_query_id": callback_id})

    async def send_message(self, text: str) -> None:
        """Deliver text and the fixed alarm-control keyboard to the configured chat."""
        await self._call(
            "sendMessage",
            {
                "chat_id": self._allowed_chat_id,
                "text": text,
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {"text": "Arm", "callback_data": "arm"},
                            {"text": "Disarm", "callback_data": "disarm"},
                            {"text": "Status", "callback_data": "status"},
                        ]
                    ]
                },
            },
        )

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        """Call one Bot API method without exposing tokenized request details."""
        try:
            url = f"{self._base_url}/bot{self._bot_token.get_secret_value()}/{method}"
            if method == "getUpdates":
                response = await self._client.get(url, params=payload)
            else:
                response = await self._client.post(url, json=payload)
            response.raise_for_status()
            envelope = response.json()
        except httpx.HTTPStatusError as error:
            raise TelegramError(method, error.response.status_code) from None
        except (httpx.HTTPError, ValueError):
            raise TelegramError(method) from None

        if not isinstance(envelope, Mapping) or envelope.get("ok") is not True or "result" not in envelope:
            raise TelegramError(method, response.status_code)
        return envelope["result"]

    def _parse_update(self, payload: Any) -> TelegramUpdate:
        """Normalize one Bot API update while enforcing chat authorization."""
        if not isinstance(payload, Mapping):
            raise TelegramError("getUpdates")
        update_id = payload.get("update_id")
        if not isinstance(update_id, int) or isinstance(update_id, bool) or update_id < 0:
            raise TelegramError("getUpdates")

        message = payload.get("message")
        if isinstance(message, Mapping):
            return self._parse_message(update_id, message)

        callback = payload.get("callback_query")
        if isinstance(callback, Mapping):
            return self._parse_callback(update_id, callback)

        return TelegramUpdate(update_id=update_id)

    def _parse_message(self, update_id: int, message: Mapping[str, Any]) -> TelegramUpdate:
        """Normalize a text message and allow its action only for the configured chat."""
        chat_id = self._chat_id(message)
        action = self._text_action(message.get("text")) if chat_id == self._allowed_chat_id else None
        return TelegramUpdate(update_id=update_id, chat_id=chat_id, action=action)

    def _parse_callback(self, update_id: int, callback: Mapping[str, Any]) -> TelegramUpdate:
        """Normalize a callback query and retain authorized acknowledgement IDs."""
        message = callback.get("message")
        chat_id = self._chat_id(message) if isinstance(message, Mapping) else None
        if chat_id != self._allowed_chat_id:
            return TelegramUpdate(update_id=update_id, chat_id=chat_id)

        callback_id = callback.get("id")
        retained_callback_id = callback_id if isinstance(callback_id, str) else None
        return TelegramUpdate(
            update_id=update_id,
            chat_id=chat_id,
            action=self._callback_action(callback.get("data")),
            callback_id=retained_callback_id,
        )

    @staticmethod
    def _chat_id(message: Mapping[str, Any]) -> int | None:
        chat = message.get("chat")
        if not isinstance(chat, Mapping):
            return None
        chat_id = chat.get("id")
        return chat_id if isinstance(chat_id, int) and not isinstance(chat_id, bool) else None

    @staticmethod
    def _text_action(text: Any) -> AlarmAction | None:
        if not isinstance(text, str):
            return None
        command = text.split(maxsplit=1)[0].split("@", maxsplit=1)[0]
        return TelegramClient._action(command.removeprefix("/"))

    @staticmethod
    def _callback_action(data: Any) -> AlarmAction | None:
        return TelegramClient._action(data) if isinstance(data, str) else None

    @staticmethod
    def _action(value: str) -> AlarmAction | None:
        try:
            return AlarmAction(value)
        except ValueError:
            return None
