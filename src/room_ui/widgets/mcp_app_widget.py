"""QFrame embedding an MCP App inside a QWebEngineView.

Falls back to a plain text label when ``PySide6.QtWebEngineWidgets`` is
not available (e.g. headless environments or minimal installs).

Architecture
~~~~~~~~~~~~
MCP Apps expect to run inside an iframe and communicate with the host via
``window.parent.postMessage``.  We replicate this in Qt by:

1. A lightweight ``http://127.0.0.1`` server hosts the wrapper and app HTML
   (``file://`` origins break ES-module width measurement in Chromium).
2. The wrapper loads ``qrc:///qtwebchannel/qwebchannel.js`` (Qt-provided)
   and contains the bridge script connecting ``QWebChannel`` ↔ ``postMessage``.
3. The MCP App HTML is loaded inside an ``<iframe>`` in the wrapper.
4. ``postMessage`` between the iframe and wrapper works natively; the wrapper
   forwards messages to/from the Python ``MCPAppBridge`` via ``QWebChannel``.
"""

from __future__ import annotations

import logging
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from room_ui.theme import colors

logger = logging.getLogger(__name__)

# Try importing WebEngine — it's an optional heavy dependency.
try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView

    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False

# Default height for the embedded view.  The app can request a different
# size via the ``ui/notifications/size-changed`` message; until then the
# view uses this fixed height so the native QWebEngine surface stays
# properly clipped inside the scroll area.
_DEFAULT_VIEW_HEIGHT = 350

# ---------------------------------------------------------------------------
# Lightweight HTTP server for MCP App content
# ---------------------------------------------------------------------------
# file:// origins break ES-module width measurement in Chromium
# (document.documentElement.getBoundingClientRect().width returns 0 under
# fit-content).  Serving via http://127.0.0.1 avoids this entirely.


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
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.debug("MCPAppHTTP: %s", format % args)


class _AppHTTPServer(HTTPServer):
    """HTTPServer with an attached content_map."""

    content_map: dict[str, str]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _AppHTTPHandler)
        self.content_map = {}


# Module-level singleton — lazily started on first use.
_http_server: _AppHTTPServer | None = None
_http_lock = threading.Lock()


def _get_http_server() -> _AppHTTPServer:
    """Return the shared HTTP server, starting it on first call."""
    global _http_server  # noqa: PLW0603
    if _http_server is not None:
        return _http_server
    with _http_lock:
        if _http_server is not None:
            return _http_server
        srv = _AppHTTPServer()
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        _http_server = srv
        logger.info("MCPAppHTTP: server started on port %d", srv.server_address[1])
        return srv


# ---------------------------------------------------------------------------
# Wrapper HTML template
# ---------------------------------------------------------------------------

_WRAPPER_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; }}
  html, body {{ width: 100%; height: 100%; overflow: hidden;
                background: {bg_color}; }}
  iframe {{ width: 100%; height: 100%; border: none; box-sizing: border-box; }}
</style>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
</head>
<body>
<iframe id="app" src="{app_url}"></iframe>
<script>
(function() {{
    "use strict";
    var iframe = document.getElementById("app");

    new QWebChannel(qt.webChannelTransport, function(channel) {{
        var bridge = channel.objects.bridge;
        console.log("[mcp-bridge] QWebChannel connected");

        // iframe -> Python: forward postMessage to bridge
        window.addEventListener("message", function(event) {{
            if (event.source === iframe.contentWindow) {{
                var json = (typeof event.data === "string")
                    ? event.data : JSON.stringify(event.data);
                bridge.receiveMessage(json);
            }}
        }});

        // Python -> iframe: forward bridge messages to iframe
        bridge.messageToApp.connect(function(jsonStr) {{
            try {{
                var data = JSON.parse(jsonStr);
                iframe.contentWindow.postMessage(data, "*");
            }} catch(e) {{
                console.error("[mcp-bridge] bad JSON from host", e);
            }}
        }});

        // Measure actual rendered content height in the iframe and
        // report it so the host widget can fit tightly around the content.
        var lastH = 0, stable = 0;
        function measureHeight() {{
            try {{
                var doc = iframe.contentDocument;
                if (!doc || !doc.body) return;
                var h = doc.body.scrollHeight;
                if (h > 50 && Math.abs(h - lastH) > 10) {{
                    lastH = h;
                    stable = 0;
                    bridge.receiveMessage(JSON.stringify({{
                        method: "ui/notifications/size-changed",
                        params: {{width: iframe.clientWidth, height: h}}
                    }}));
                }} else {{
                    stable++;
                    if (stable > 20) clearInterval(htid);
                }}
            }} catch(e) {{}}
        }}
        var htid = setInterval(measureHeight, 500);
        iframe.addEventListener("load", function() {{
            setTimeout(measureHeight, 300);
        }});
    }});
}})();
</script>
</body>
</html>
"""


def has_webengine() -> bool:
    """Return True if QWebEngine is importable."""
    return _HAS_WEBENGINE


# ---------------------------------------------------------------------------
# Custom page that forwards JS console to Python logging
# ---------------------------------------------------------------------------
if _HAS_WEBENGINE:

    class _DebugPage(QWebEnginePage):  # type: ignore[misc]
        """QWebEnginePage that logs JS console messages to Python."""

        def javaScriptConsoleMessage(  # noqa: N802
            self,
            level: QWebEnginePage.JavaScriptConsoleMessageLevel,
            message: str,
            line: int,
            source: str,
        ) -> None:
            lvl: int = level.value  # type: ignore[union-attr]
            # Only log warnings/errors and short info messages to avoid
            # flooding the log with minified HTML/JS from MCP Apps.
            if lvl >= 1:
                tag = {1: "JS WARN", 2: "JS ERR"}.get(lvl, "JS")
                logger.warning("[%s] %s (line %d)", tag, message[:300], line)
            elif len(message) < 500:
                logger.debug("[JS] %s", message[:200])


class MCPAppWidget(QFrame):
    """Sandboxed container for an MCP App.

    If QWebEngine is available, renders the HTML in a ``QWebEngineView``
    with a ``QWebChannel``-backed bridge.  Otherwise shows a fallback label.
    """

    tool_call_requested = Signal(str, str, dict)  # request_id, tool_name, arguments

    def __init__(
        self,
        tool_name: str,
        server_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool_name = tool_name
        self._server_name = server_name
        self._bridge: Any = None  # MCPAppBridge (set up only when WebEngine is used)
        self._view: Any = None  # QWebEngineView | None
        self._http_paths: list[str] = []  # HTTP paths to clean up
        self._fullscreen_dialog: QDialog | None = None

        # Expand horizontally to fill the scroll area; fixed height.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        c = colors()
        self.setStyleSheet(
            f"MCPAppWidget {{"
            f"  background: {c['BG_TERTIARY']};"
            f"  border: 1px solid {c['SEPARATOR']};"
            f"  border-radius: 8px;"
            f"  margin: 4px 20px;"
            f"}}"
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Header — show the MCP server name (e.g. "Excalidraw"), like Claude does
        header = QLabel(f"\u2699  {server_name}")
        header.setStyleSheet(
            "QLabel {"
            "  color: #BF5AF2;"
            "  font-size: 12px;"
            "  background: transparent;"
            "  padding: 6px 12px 2px 12px;"
            "}"
        )
        self._layout.addWidget(header)

        if _HAS_WEBENGINE:
            try:
                self._setup_webengine()
            except Exception:
                logger.exception("QWebEngine init failed — falling back to text label")
                self._add_fallback()
        else:
            self._add_fallback()

    def _add_fallback(self) -> None:
        c = colors()
        label = QLabel("MCP App (QWebEngine not available)")
        label.setStyleSheet(
            f"color: {c['TEXT_SECONDARY']}; padding: 12px; background: transparent;"
        )
        self._layout.addWidget(label)

    def _setup_webengine(self) -> None:
        from room_ui.mcp_app_bridge import MCPAppBridge

        logger.debug("MCPAppWidget: setting up QWebEngine for %r", self._tool_name)

        # Off-the-record profile (no persistent storage)
        profile = QWebEngineProfile(self)
        page = _DebugPage(profile, self)

        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)

        # Set page background to match the app theme so the view doesn't
        # flash black while the HTML loads.
        c = colors()
        self._page_bg = c["BG_TERTIARY"]
        page.setBackgroundColor(QColor(self._page_bg))

        # Set up QWebChannel with bridge
        self._bridge = MCPAppBridge(self._tool_name, self._server_name, self)
        channel = QWebChannel(self)
        channel.registerObject("bridge", self._bridge)
        page.setWebChannel(channel)

        # Forward bridge signals
        self._bridge.tool_call_requested.connect(self.tool_call_requested)
        self._bridge.size_changed.connect(self._on_size_changed)
        self._bridge.display_mode_requested.connect(self._on_display_mode)

        # Create the view with a *fixed* height so the native Chromium
        # surface stays properly clipped inside the scroll area.
        self._view = QWebEngineView(self)
        self._view.setPage(page)
        self._view.setFixedHeight(_DEFAULT_VIEW_HEIGHT)
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._view.loadFinished.connect(self._on_load_finished)
        self._layout.addWidget(self._view)
        logger.debug("MCPAppWidget: QWebEngine view created")

    def load_html(self, html_content: str) -> None:
        """Load the MCP App HTML into the embedded view.

        Registers two paths on the shared HTTP server:
        - ``/<token>/app.html``     — the raw MCP App HTML
        - ``/<token>/wrapper.html`` — host page with ``<iframe>`` + bridge

        Serving via ``http://127.0.0.1`` instead of ``file://`` avoids
        Chromium's broken width measurement under file:// origins.
        """
        if self._view is None:
            return

        try:
            srv = _get_http_server()
            host, port = srv.server_address[:2]

            # Unique token so multiple widgets don't collide
            token = secrets.token_hex(8)
            app_path = f"/{token}/app.html"
            wrapper_path = f"/{token}/wrapper.html"

            # Register content on the HTTP server
            srv.content_map[app_path] = html_content

            bg = getattr(self, "_page_bg", "#3A3A3C")
            # app_url is relative — same origin, same directory
            wrapper_html = _WRAPPER_HTML.format(app_url="app.html", bg_color=bg)
            srv.content_map[wrapper_path] = wrapper_html

            self._http_paths = [app_path, wrapper_path]

            url = f"http://{host!s}:{port}{wrapper_path}"
            logger.debug("MCPAppWidget: loading %s (app=%d bytes)", url, len(html_content))
            self._view.load(QUrl(url))

        except Exception:
            logger.exception("Failed to serve MCP App HTML")

    def send_tool_input(self, arguments: dict[str, Any]) -> None:
        """Push tool-call arguments into the app."""
        if self._bridge is not None:
            self._bridge.send_tool_input(arguments)

    def send_tool_result(self, result: Any) -> None:
        """Push tool-call result into the app."""
        if self._bridge is not None:
            self._bridge.send_tool_result(result)

    def send_tool_call_response(self, request_id: str, result: str) -> None:
        """Return a tools/call response to the app."""
        if self._bridge is not None:
            self._bridge.send_tool_call_response(request_id, result)

    def _on_display_mode(self, mode: str) -> None:
        if mode == "fullscreen" and self._fullscreen_dialog is None:
            self._enter_fullscreen()

    def _enter_fullscreen(self) -> None:
        if self._view is None:
            return

        dialog = QDialog(self.window())
        dialog.setWindowTitle(f"\u2699  {self._server_name}")

        c = colors()
        bg = getattr(self, "_page_bg", c["BG_TERTIARY"])
        dialog.setStyleSheet(f"QDialog {{ background: {bg}; }}")

        # Size to ~80% of available screen
        screen = self.screen()
        if screen:
            geom = screen.availableGeometry()
            dialog.resize(int(geom.width() * 0.8), int(geom.height() * 0.8))
        else:
            dialog.resize(900, 700)

        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(0, 0, 0, 0)

        # Reparent view from inline widget to dialog
        self._layout.removeWidget(self._view)
        self._view.setMinimumHeight(0)
        self._view.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self._view)

        self._fullscreen_dialog = dialog
        dialog.finished.connect(self._exit_fullscreen)
        dialog.show()

    def _exit_fullscreen(self) -> None:
        dialog = self._fullscreen_dialog
        if dialog is None or self._view is None:
            return

        # Reparent view back to inline widget
        lay = dialog.layout()
        if lay is not None:
            lay.removeWidget(self._view)
        self._view.setFixedHeight(_DEFAULT_VIEW_HEIGHT)
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._layout.addWidget(self._view)

        self._fullscreen_dialog = None
        dialog.deleteLater()

        # Notify app that host switched back to inline
        if self._bridge is not None:
            self._bridge.notify_host_context_changed(displayMode="inline")

    def _on_load_finished(self, ok: bool) -> None:
        url = self._view.url().toString() if self._view else "?"
        logger.info("MCPAppWidget: loadFinished ok=%s url=%s", ok, url)

    def _on_size_changed(self, width: int, height: int) -> None:
        # Don't resize the inline view while in fullscreen mode
        if self._fullscreen_dialog is not None or self._view is None:
            return
        clamped = max(200, min(height, 800))
        self._view.setFixedHeight(clamped)
        logger.debug(
            "MCPAppWidget: size changed %dx%d (clamped h=%d)",
            width,
            height,
            clamped,
        )

    def _cleanup_http(self) -> None:
        if _http_server is not None:
            for path in self._http_paths:
                _http_server.content_map.pop(path, None)
        self._http_paths.clear()

    def deleteLater(self) -> None:  # noqa: N802
        if self._fullscreen_dialog is not None:
            self._fullscreen_dialog.close()
            self._fullscreen_dialog = None
        self._cleanup_http()
        super().deleteLater()
