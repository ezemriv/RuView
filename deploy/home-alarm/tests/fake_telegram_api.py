"""Small Bot API-compatible HTTP service for the Compose smoke test."""

import argparse
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

_MAX_BODY_BYTES = 1_048_576


class _Store:
    """Thread-safe in-memory observations without retaining Bot API credentials."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.updates: list[dict[str, Any]] = []
        self.messages: list[str] = []
        self.acknowledgements: list[str] = []


class FakeTelegramHandler(BaseHTTPRequestHandler):
    """Serve the Bot API subset and test-only control endpoints."""

    store = _Store()

    def do_GET(self) -> None:  # noqa: N802
        """Return readiness, observations, or queued Telegram updates."""
        target = urlsplit(self.path)
        if target.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if target.path == "/messages":
            with self.store.condition:
                payload = {
                    "messages": list(self.store.messages),
                    "acknowledgements": list(self.store.acknowledgements),
                }
            self._json(HTTPStatus.OK, payload)
            return
        if target.path.endswith("/getUpdates"):
            query = parse_qs(target.query)
            try:
                offset = int(query.get("offset", ["0"])[0])
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "result": False})
                return
            with self.store.condition:
                updates = [item for item in self.store.updates if item["update_id"] >= offset]
                if not updates:
                    self.store.condition.wait(timeout=0.25)
                    updates = [item for item in self.store.updates if item["update_id"] >= offset]
            self._json(HTTPStatus.OK, {"ok": True, "result": updates})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        """Enqueue a test update or record one Bot API side effect."""
        target = urlsplit(self.path)
        try:
            payload = self._read_json()
        except (json.JSONDecodeError, UnicodeError, ValueError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad request"})
            return
        if target.path == "/enqueue":
            update_id = payload.get("update_id")
            if not isinstance(update_id, int) or isinstance(update_id, bool) or update_id < 0:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid update"})
                return
            with self.store.condition:
                self.store.updates.append(payload)
                self.store.condition.notify_all()
            self._json(HTTPStatus.OK, {"queued": True})
            return
        if target.path.endswith("/sendMessage"):
            text = payload.get("text")
            if not isinstance(text, str):
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "result": False})
                return
            with self.store.condition:
                self.store.messages.append(text)
            self._json(
                HTTPStatus.OK,
                {"ok": True, "result": {"message_id": len(self.store.messages)}},
            )
            return
        if target.path.endswith("/answerCallbackQuery"):
            callback_id = payload.get("callback_query_id")
            if not isinstance(callback_id, str):
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "result": False})
                return
            with self.store.condition:
                self.store.acknowledgements.append(callback_id)
            self._json(HTTPStatus.OK, {"ok": True, "result": True})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length < 0 or content_length > _MAX_BODY_BYTES:
            raise ValueError("body too large")
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("object required")
        return payload

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress request logging so tokenized Bot API paths are never emitted."""


def main() -> None:
    """Serve until the container runtime terminates the process."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), FakeTelegramHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
