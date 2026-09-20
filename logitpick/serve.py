"""Loopback HTTP wrapper. Refuses non-localhost binds."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .engine import pick
from .ollama import OllamaBackend, OllamaError
from .schema import PickError, parse_request

MAX_BODY = 64 * 1024


class PickHandler(BaseHTTPRequestHandler):
    backend: Any = None

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/health":
            self._send(200, {"ok": True, "bind": "127.0.0.1"})
            return
        self._send(404, {"code": "not_found", "message": "no such path"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/v1/pick":
            self._send(404, {"code": "not_found", "message": "no such path"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > MAX_BODY:
            self._send(413, {"code": "body_too_large", "message": f"max {MAX_BODY} bytes"})
            return
        try:
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"code": "malformed", "message": "body must be JSON"})
            return
        try:
            req = parse_request(raw)
            result = pick(req, self.backend)
        except PickError as e:
            self._send(422, e.as_dict())
            return
        except OllamaError as e:
            self._send(502, {"code": "upstream", "message": str(e)})
            return
        self._send(200, result)


def serve(host: str, port: int, backend: Any | None = None) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("refusing to bind off loopback")
    PickHandler.backend = backend or OllamaBackend()
    httpd = ThreadingHTTPServer((host, port), PickHandler)
    return httpd
