"""Minimal HTTP gateway for MiniCode.

The gateway intentionally uses only the standard library so the Docker and
console entry points remain zero-dependency. It exposes a health endpoint and a
small headless execution endpoint for platform bridges to build on.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _json_bytes(payload: dict[str, Any], status: int = 200) -> tuple[int, bytes]:
    return status, json.dumps(payload, ensure_ascii=False).encode("utf-8")


class MiniCodeGatewayHandler(BaseHTTPRequestHandler):
    server_version = "MiniCodeGateway/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if os.environ.get("MINI_CODE_GATEWAY_ACCESS_LOG") == "1":
            super().log_message(format, *args)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        status_code, body = _json_bytes(payload, status)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/health"}:
            self._send_json({"ok": True, "service": "minicode-gateway"})
            return
        self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/run":
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw) if raw.strip() else {}
            prompt = str(data.get("prompt", "")).strip()
            if not prompt:
                self._send_json({"ok": False, "error": "prompt is required"}, status=400)
                return

            from minicode.headless import run_headless

            self._send_json({"ok": True, "response": run_headless(prompt)})
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc)}, status=500)


def run_gateway() -> None:
    host = os.environ.get("MINI_CODE_GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("MINI_CODE_GATEWAY_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), MiniCodeGatewayHandler)
    print(f"MiniCode gateway listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_gateway()
