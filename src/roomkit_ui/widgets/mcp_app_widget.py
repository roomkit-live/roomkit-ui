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
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from roomkit_ui.theme import colors
from roomkit_ui.theme_live import themed_style
from roomkit_ui.widgets.mcp_app_server import get_http_server, release_content
from roomkit_ui.widgets.mcp_app_wrapper import WRAPPER_HTML

logger = logging.getLogger(__name__)

# Try importing WebEngine — it's an optional heavy dependency.
try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    from roomkit_ui.widgets.mcp_app_web import AppPage, AppRequestInterceptor, set_web_attribute

    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False

# Default height for the embedded view.  The app can request a different
# size via the ``ui/notifications/size-changed`` message; until then the
# view uses this fixed height so the native QWebEngine surface stays
# properly clipped inside the scroll area.
_DEFAULT_VIEW_HEIGHT = 350


def has_webengine() -> bool:
    """Return True if QWebEngine is importable."""
    return _HAS_WEBENGINE


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
        self._page: Any = None  # AppPage | None
        self._request_interceptor: Any = None  # AppRequestInterceptor | None
        self._http_paths: list[str] = []  # HTTP paths to clean up
        self._fullscreen_dialog: QDialog | None = None

        # Expand horizontally to fill the scroll area; fixed height.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # ToolActivity owns the frame, title and status for every kind of tool.
        self.setStyleSheet("MCPAppWidget { background: transparent; border: none; }")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Error label — hidden by default, shown on JS errors
        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        themed_style(
            self._error_label,
            lambda c: (
                f"color: {c['ACCENT_RED']}; font-size: 11px;"
                "background: transparent; padding: 4px 12px;"
            ),
        )
        self._error_label.hide()

        if _HAS_WEBENGINE:
            try:
                self._setup_webengine()
            except Exception:
                logger.exception("QWebEngine init failed — falling back to text label")
                self._add_fallback()
        else:
            self._add_fallback()

        self._layout.addWidget(self._error_label)

    def _add_fallback(self) -> None:
        label = QLabel("MCP App (QWebEngine not available)")
        themed_style(
            label,
            lambda c: f"color: {c['TEXT_SECONDARY']}; padding: 12px; background: transparent;",
        )
        self._layout.addWidget(label)

    def _setup_webengine(self) -> None:
        logger.debug("MCPAppWidget: setting up QWebEngine for %r", self._tool_name)

        # Off-the-record profile (no persistent storage), one per widget so no
        # two MCP Apps share storage — they all live on the same origin.
        # Parented last: Qt deletes children in the order they were added, and
        # a profile added before its page went first ("Release of profile
        # requested but WebEnginePage still not deleted", and possible crashes).
        profile = QWebEngineProfile()
        try:
            self._setup_page_and_view(profile)
        finally:
            profile.setParent(self)

    def _setup_page_and_view(self, profile: QWebEngineProfile) -> None:
        from roomkit_ui.mcp_app_bridge import MCPAppBridge

        profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        self._request_interceptor = AppRequestInterceptor(self)
        profile.setUrlRequestInterceptor(self._request_interceptor)
        page = AppPage(profile, self)
        self._page = page
        page.js_error.connect(self._on_js_error)

        settings = page.settings()
        set_web_attribute(settings, "JavascriptEnabled", True)
        set_web_attribute(settings, "WebGLEnabled", True)
        set_web_attribute(settings, "LocalContentCanAccessRemoteUrls", False)
        set_web_attribute(settings, "LocalContentCanAccessFileUrls", False)
        set_web_attribute(settings, "JavascriptCanOpenWindows", False)
        set_web_attribute(settings, "PluginsEnabled", False)
        set_web_attribute(settings, "WebRTCPublicInterfacesOnly", True)

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
            srv = get_http_server()
            host, port = srv.server_address[:2]

            # Unique token so multiple widgets don't collide
            token = secrets.token_hex(8)
            app_path = f"/{token}/app.html"
            wrapper_path = f"/{token}/wrapper.html"

            # Register content on the HTTP server
            srv.content_map[app_path] = html_content

            bg = getattr(self, "_page_bg", "#3A3A3C")
            # app_url is relative — same origin, same directory
            wrapper_html = WRAPPER_HTML.format(app_url="app.html", bg_color=bg)
            srv.content_map[wrapper_path] = wrapper_html

            self._http_paths = [app_path, wrapper_path]

            url = f"http://{host!s}:{port}{wrapper_path}"
            allowed_host = str(host).lower()
            if self._request_interceptor is not None:
                self._request_interceptor.set_allowed_local_server(allowed_host, int(port))
            if self._page is not None:
                self._page.set_allowed_app_paths(allowed_host, int(port), {app_path, wrapper_path})
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
        logger.info("MCPAppWidget: loadFinished ok=%s", ok)
        logger.debug("MCPAppWidget: loadFinished url=%s", url)

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

    def _on_js_error(self, message: str) -> None:
        """Show a JS error message in the error label below the web view."""
        self._error_label.setText(f"JS Error: {message}")
        self._error_label.show()

    def _cleanup_http(self) -> None:
        release_content(self._http_paths)
        self._http_paths.clear()

    def deleteLater(self) -> None:  # noqa: N802
        if self._fullscreen_dialog is not None:
            self._fullscreen_dialog.close()
            self._fullscreen_dialog = None
        self._cleanup_http()
        super().deleteLater()
