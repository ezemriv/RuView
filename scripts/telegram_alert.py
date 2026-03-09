"""Telegram alert service for RuView home security.

Connects to the sensing server's REST API, monitors presence state,
and sends Telegram notifications on state transitions.

Supports arming/disarming via Telegram inline keyboard buttons.
Commands: /arm, /disarm, /status
"""

from __future__ import annotations

import logging
import os
import sys
import time
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import urlencode
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("telegram_alert")

POLL_INTERVAL = 5  # seconds
CLEAR_DELAY = 60  # seconds of no presence before "all clear"
SENSING_URL = os.getenv("SENSING_URL", "http://localhost:3000/api/v1/sensing/latest")
BOT_POLL_INTERVAL = 1  # seconds between Telegram update checks


def get_env_or_exit(key: str) -> str:
    val = os.getenv(key)
    if not val:
        logger.error(f"Missing required environment variable: {key}")
        sys.exit(1)
    return val


def telegram_api(token: str, method: str, payload: dict) -> dict | None:
    """Call Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode()
    try:
        req = Request(url, data=data, method="POST",
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        logger.exception(f"Telegram API error: {method}")
        return None


def send_message(token: str, chat_id: str, text: str,
                 keyboard: list[list[dict]] | None = None) -> None:
    """Send a Telegram message, optionally with inline keyboard."""
    payload: dict = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    result = telegram_api(token, "sendMessage", payload)
    if result:
        logger.info(f"Telegram sent: {text}")


def answer_callback(token: str, callback_id: str, text: str) -> None:
    """Acknowledge a callback query (button press)."""
    telegram_api(token, "answerCallbackQuery",
                 {"callback_query_id": callback_id, "text": text})


def status_keyboard() -> list[list[dict]]:
    """Inline keyboard with Arm / Disarm / Status buttons."""
    return [
        [
            {"text": "Arm", "callback_data": "arm"},
            {"text": "Disarm", "callback_data": "disarm"},
        ],
        [
            {"text": "Status", "callback_data": "status"},
        ],
    ]


def fetch_sensing() -> dict | None:
    """Fetch latest sensing data. Returns None if unavailable."""
    try:
        req = Request(SENSING_URL, method="GET")
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (URLError, OSError):
        return None
    except Exception:
        logger.exception("Error fetching sensing data")
        return None


class AlarmState:
    """Thread-safe alarm state."""

    def __init__(self) -> None:
        self.armed = False
        self.presence = False
        self.last_presence_time: float = 0.0
        self.clear_sent = True
        self.lock = threading.Lock()


def bot_listener(token: str, chat_id: str, state: AlarmState) -> None:
    """Long-poll Telegram for commands and button presses."""
    offset = 0

    while True:
        try:
            result = telegram_api(token, "getUpdates", {
                "offset": offset, "timeout": 20, "allowed_updates": ["message", "callback_query"]
            })
            if not result or not result.get("ok"):
                time.sleep(BOT_POLL_INTERVAL)
                continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1

                # Handle button presses
                cb = update.get("callback_query")
                if cb:
                    from_id = str(cb["from"]["id"])
                    if from_id != chat_id:
                        continue
                    action = cb.get("data", "")
                    _handle_action(token, chat_id, state, action, cb["id"])
                    continue

                # Handle text commands
                msg = update.get("message", {})
                from_id = str(msg.get("from", {}).get("id", ""))
                if from_id != chat_id:
                    continue
                text = msg.get("text", "").strip().lower()
                if text in ("/arm", "/disarm", "/status", "/start"):
                    action = text.lstrip("/")
                    if action == "start":
                        action = "status"
                    _handle_action(token, chat_id, state, action)

        except Exception:
            logger.exception("Bot listener error")
            time.sleep(5)


def _handle_action(token: str, chat_id: str, state: AlarmState,
                   action: str, callback_id: str | None = None) -> None:
    """Process arm/disarm/status actions."""
    with state.lock:
        if action == "arm":
            state.armed = True
            state.presence = False
            state.clear_sent = True
            msg = "Armed — motion alerts are ON"
            logger.info("Alarm ARMED")
        elif action == "disarm":
            state.armed = False
            state.presence = False
            state.clear_sent = True
            msg = "Disarmed — motion alerts are OFF"
            logger.info("Alarm DISARMED")
        elif action == "status":
            armed_str = "ARMED" if state.armed else "DISARMED"
            presence_str = "Yes" if state.presence else "No"
            msg = f"Status: {armed_str}\nPresence detected: {presence_str}"
        else:
            return

    if callback_id:
        answer_callback(token, callback_id, msg.split("\n")[0])
    send_message(token, chat_id, msg, keyboard=status_keyboard())


def main() -> None:
    token = get_env_or_exit("TELEGRAM_BOT_TOKEN")
    chat_id = get_env_or_exit("TELEGRAM_CHAT_ID")

    state = AlarmState()

    logger.info("Telegram alert service starting...")
    logger.info(f"Polling {SENSING_URL} every {POLL_INTERVAL}s")

    # Start bot listener in background thread
    bot_thread = threading.Thread(target=bot_listener, args=(token, chat_id, state),
                                 daemon=True)
    bot_thread.start()
    logger.info("Bot listener started (use /arm, /disarm, /status or buttons)")

    # Wait for sensing server to be ready
    while True:
        data = fetch_sensing()
        if data is not None:
            logger.info("Sensing server is ready")
            send_message(token, chat_id,
                         "RuView alarm system started\nUse the buttons below to arm/disarm:",
                         keyboard=status_keyboard())
            break
        logger.info("Waiting for sensing server...")
        time.sleep(2)

    while True:
        data = fetch_sensing()
        if data is None:
            time.sleep(POLL_INTERVAL)
            continue

        with state.lock:
            if not state.armed:
                time.sleep(POLL_INTERVAL)
                continue

            classification = data.get("classification", {})
            current_presence = bool(classification.get("presence", False))
            now = time.time()

            if current_presence and not state.presence:
                state.presence = True
                state.clear_sent = False
                state.last_presence_time = now
                logger.info("Motion DETECTED (armed)")
                send_message(token, chat_id,
                             "\U0001f6a8\U0001f6a8\U0001f6a8 INTRUSION ALERT \U0001f6a8\U0001f6a8\U0001f6a8\n\n"
                             "\u26a0\ufe0f MOTION DETECTED AT HOME\n\n"
                             "Check cameras immediately!",
                             keyboard=status_keyboard())

            elif current_presence:
                state.last_presence_time = now

            elif not current_presence and state.presence:
                if now - state.last_presence_time >= CLEAR_DELAY:
                    state.presence = False
                    if not state.clear_sent:
                        state.clear_sent = True
                        logger.info("All clear — no motion for 60s")
                        send_message(token, chat_id,
                                     "\u2705 All clear — no more motion detected",
                                     keyboard=status_keyboard())

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
