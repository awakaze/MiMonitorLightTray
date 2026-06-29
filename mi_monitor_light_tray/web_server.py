"""Optional HTTP server exposing the lamp over the local network.

Runs in a background daemon thread so the tray app keeps owning the main
event loop. The handler reuses ``MiMonitorLight``'s existing thread-safety —
every call goes through the same internal lock the tray UI uses, so an HTTP
client and a slider drag can't race.

Endpoints (all return JSON):

    GET  /api/state                        — current cached state
    POST /api/refresh                      — force a network read, return fresh state
    POST /api/power            {"on": bool}
    POST /api/toggle
    POST /api/brightness       {"value": int}    1..100
    POST /api/color_temp       {"value": int}    model-dependent range
    GET  /api/limits                       — brightness/CT min/max + model

    GET  /                                 — bundled control page
    GET  /favicon.ico                      — 204

Auth: if ``token`` is set, every /api/* request must carry
``Authorization: Bearer <token>`` OR ``?token=<token>``. The bundled HTML
auto-appends the query-string variant so a bookmark works.
"""

from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)


_UI_HTML_PATH = Path(__file__).resolve().parent / "web_ui.html"


def _load_ui_html() -> bytes:
    try:
        return _UI_HTML_PATH.read_bytes()
    except OSError as exc:
        log.warning("web_ui.html missing: %s", exc)
        return b"<!doctype html><meta charset=utf-8><title>UI missing</title><p>web_ui.html not found"


class _Handler(BaseHTTPRequestHandler):
    server_version = "MiMonitorLight/1.0"

    # Injected by WebServer before serve_forever
    light = None  # type: ignore[assignment]
    auth_token: str = ""
    ui_bytes: bytes = b""

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("%s - " + fmt, self.address_string(), *args)

    # ---- helpers ----

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _authorized(self, query: dict) -> bool:
        if not self.auth_token:
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            if header[len("Bearer "):].strip() == self.auth_token:
                return True
        token_qs = query.get("token", [""])[0]
        return token_qs == self.auth_token

    def _state_payload(self) -> dict:
        st = self.light.state
        return {
            "is_on": bool(st.is_on),
            "brightness": int(st.brightness),
            "color_temp": int(st.color_temp),
            "reachable": bool(st.reachable),
            "error": st.error,
            "model": getattr(self.light, "model", ""),
            "brightness_min": self.light.BRIGHTNESS_MIN,
            "brightness_max": self.light.BRIGHTNESS_MAX,
            "color_temp_min": self.light.color_temp_min,
            "color_temp_max": self.light.color_temp_max,
        }

    # ---- routing ----

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        query = parse_qs(url.query)
        path = url.path

        if path in ("/", "/index.html"):
            self._send_html(self.ui_bytes)
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        if not path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized(query):
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        if path == "/api/state":
            self._send_json(HTTPStatus.OK, self._state_payload())
            return
        if path == "/api/limits":
            self._send_json(HTTPStatus.OK, {
                "brightness_min": self.light.BRIGHTNESS_MIN,
                "brightness_max": self.light.BRIGHTNESS_MAX,
                "color_temp_min": self.light.color_temp_min,
                "color_temp_max": self.light.color_temp_max,
                "model": getattr(self.light, "model", ""),
            })
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        query = parse_qs(url.query)
        path = url.path

        if not path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized(query):
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        try:
            body = self._read_json() if int(self.headers.get("Content-Length") or 0) > 0 else {}
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        try:
            if path == "/api/refresh":
                self.light.refresh()
            elif path == "/api/power":
                if "on" not in body or not isinstance(body["on"], bool):
                    raise ValueError("'on' must be a boolean")
                self.light.set_power(body["on"])
            elif path == "/api/toggle":
                self.light.toggle()
            elif path == "/api/brightness":
                value = body.get("value")
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError("'value' must be an integer")
                self.light.set_brightness(value)
            elif path == "/api/color_temp":
                value = body.get("value")
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError("'value' must be an integer")
                self.light.set_color_temp(value)
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("API call failed: %s %s", path, exc)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        self._send_json(HTTPStatus.OK, self._state_payload())


class WebServer:
    """Daemon-threaded HTTP server bound to a ``MiMonitorLight`` instance."""

    def __init__(self, light, host: str = "0.0.0.0", port: int = 8765,
                 token: str = "") -> None:
        self._light = light
        self._host = host
        self._port = int(port)
        self._token = token or ""
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._ui_bytes = _load_ui_html()

    @property
    def bound_address(self) -> Optional[tuple[str, int]]:
        if self._httpd is None:
            return None
        return self._httpd.server_address[:2]

    def start(self) -> tuple[str, int]:
        if self._httpd is not None:
            return self._httpd.server_address[:2]

        light = self._light
        token = self._token
        ui_bytes = self._ui_bytes

        class _BoundHandler(_Handler):
            pass

        _BoundHandler.light = light
        _BoundHandler.auth_token = token
        _BoundHandler.ui_bytes = ui_bytes

        # Bind explicitly so the OSError surfaces here (not in the thread).
        self._httpd = ThreadingHTTPServer((self._host, self._port), _BoundHandler)
        host, port = self._httpd.server_address[:2]
        log.info("Web server listening on http://%s:%d/", host, port)

        thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="MiMonitorLight-web",
            daemon=True,
        )
        thread.start()
        self._thread = thread
        return host, port

    def stop(self) -> None:
        httpd = self._httpd
        if httpd is None:
            return
        log.info("Stopping web server")
        try:
            httpd.shutdown()
        finally:
            httpd.server_close()
            self._httpd = None
            self._thread = None

    def update_light(self, light) -> None:
        """Swap in a freshly built ``MiMonitorLight`` after a config save."""
        self._light = light
        if self._httpd is not None:
            self._httpd.RequestHandlerClass.light = light  # type: ignore[attr-defined]
