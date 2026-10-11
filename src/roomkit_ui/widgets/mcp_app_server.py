"""Local HTTP server for MCP App content.

``file://`` origins break ES-module width measurement in Chromium
(``document.documentElement.getBoundingClientRect().width`` returns 0 under
``fit-content``), so the wrapper and the app are served from
``http://127.0.0.1`` instead, with a CSP of their own.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)

APP_CSP = (
    "default-src 'self' http: https: data: blob:; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' http: https: qrc: data: blob:; "
    "style-src 'self' 'unsafe-inline' http: https: data:; "
    "img-src 'self' http: https: data: blob:; "
    "font-src 'self' http: https: data:; "
    "connect-src 'self' http: https: ws: wss:; "
    "frame-src 'self' http: https: data: blob:; "
    "worker-src 'self' blob:; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)


class _AppHTTPHandler(BaseHTTPRequestHandler):
    """Serves MCP App HTML from an in-memory dict."""

    def do_GET(self) -> None:  # noqa: N802
        content = self.server.content_map.get(self.path)  # type: ignore[attr-defined]
        if content is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", APP_CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.debug("MCPAppHTTP: %s", format % args)


class AppHTTPServer(HTTPServer):
    """HTTPServer with an attached content_map."""

    content_map: dict[str, str]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _AppHTTPHandler)
        self.content_map = {}


# Module-level singleton — lazily started on first use.
_http_server: AppHTTPServer | None = None
_http_lock = threading.Lock()


def get_http_server() -> AppHTTPServer:
    """Return the shared HTTP server, starting it on first call."""
    global _http_server  # noqa: PLW0603
    if _http_server is not None:
        return _http_server
    with _http_lock:
        if _http_server is not None:
            return _http_server
        srv = AppHTTPServer()
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        _http_server = srv
        logger.info("MCPAppHTTP: server started on port %d", srv.server_address[1])
        return srv


def release_content(paths: Iterable[str]) -> None:
    """Stop serving *paths*; a no-op when the server never started."""
    if _http_server is None:
        return
    for path in paths:
        _http_server.content_map.pop(path, None)
