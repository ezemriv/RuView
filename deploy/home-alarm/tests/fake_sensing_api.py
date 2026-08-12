"""Clearly synthetic ESP32-shaped HTTP service for the container smoke test."""

import argparse
import hmac
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

_MAX_BODY_BYTES = 1_048_576


class _Store:
    """Hold synthetic presence and credential-free request evidence."""

    def __init__(self, api_token: str) -> None:
        self.lock = threading.Lock()
        self.authorization = f"Bearer {api_token}"
        self.presence = False
        self.tick = 1
        self.authenticated_requests: dict[str, int] = {
            "/health": 0,
            "/api/v1/sensing/latest": 0,
        }


class FakeSensingHandler(BaseHTTPRequestHandler):
    """Serve authenticated synthetic sensing plus loopback-only test controls."""

    store: _Store

    def do_GET(self) -> None:  # noqa: N802
        """Return readiness, safe request evidence, or synthetic sensing data."""
        path = urlsplit(self.path).path
        if path == "/ready":
            self._json(HTTPStatus.OK, {"status": "ready"})
            return
        if path == "/requests":
            with self.store.lock:
                authenticated_requests = dict(self.store.authenticated_requests)
            self._json(
                HTTPStatus.OK,
                {"authenticated_requests": authenticated_requests},
            )
            return
        if path not in self.store.authenticated_requests:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        with self.store.lock:
            self.store.authenticated_requests[path] += 1
            tick = self.store.tick
            presence = self.store.presence
        if path == "/health":
            payload = {"status": "ok", "source": "esp32", "tick": tick, "clients": 1}
        else:
            payload = {
                "source": "esp32",
                "tick": tick,
                "classification": {"presence": presence},
            }
        self._json(HTTPStatus.OK, payload)

    def do_POST(self) -> None:  # noqa: N802
        """Set synthetic presence through a test-only control endpoint."""
        if urlsplit(self.path).path != "/presence":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            payload = self._read_json()
        except (json.JSONDecodeError, UnicodeError, ValueError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad request"})
            return
        presence = payload.get("presence")
        if type(presence) is not bool:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "boolean presence required"})
            return
        with self.store.lock:
            self.store.presence = presence
            self.store.tick += 1
            tick = self.store.tick
        self._json(HTTPStatus.OK, {"presence": presence, "tick": tick})

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, self.store.authorization)

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
        """Suppress request logging so authorization metadata is never emitted."""


def main() -> None:
    """Serve until the container runtime terminates the process."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    api_token = os.environ["RUVIEW_API_TOKEN"]
    FakeSensingHandler.store = _Store(api_token)
    del api_token
    server = ThreadingHTTPServer(("0.0.0.0", args.port), FakeSensingHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
