"""QtWebEngine pieces of the MCP App widget: request filter, page, settings.

Imported only when QtWebEngine is available (``mcp_app_widget.has_webengine``).
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWidgets import QWidget

from roomkit_ui.url_policy import is_public_web_url, safe_url_for_log

logger = logging.getLogger(__name__)


def set_web_attribute(settings: QWebEngineSettings, name: str, enabled: bool) -> None:
    attr = getattr(QWebEngineSettings.WebAttribute, name, None)
    if attr is None:
        attr = getattr(QWebEngineSettings, name, None)
    if attr is not None:
        settings.setAttribute(attr, enabled)


def _is_allowed_local_url(
    url: QUrl,
    allowed_host: str,
    allowed_port: int,
    allowed_paths: set[str] | None = None,
) -> bool:
    if url.scheme().lower() != "http":
        return False
    if url.host().lower() != allowed_host or url.port() != allowed_port:
        return False
    return allowed_paths is None or url.path() in allowed_paths


class AppRequestInterceptor(QWebEngineUrlRequestInterceptor):  # type: ignore[misc]
    """Blocks embedded MCP Apps from reaching local/private browser targets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._allowed_host = ""
        self._allowed_port = -1

    def set_allowed_local_server(self, host: str, port: int) -> None:
        self._allowed_host = host.lower()
        self._allowed_port = port

    def interceptRequest(self, info: Any) -> None:  # noqa: N802
        url = info.requestUrl()
        scheme = url.scheme().lower()
        url_str = url.toString()
        allowed = (
            scheme in {"about", "qrc", "data", "blob"}
            or _is_allowed_local_url(url, self._allowed_host, self._allowed_port)
            or is_public_web_url(url_str)
        )
        if allowed:
            return
        logger.warning("MCPAppWidget: blocked web request to %s", safe_url_for_log(url_str))
        info.block(True)


class AppPage(QWebEnginePage):  # type: ignore[misc]
    """QWebEnginePage that logs JS console messages to Python."""

    js_error = Signal(str)  # emits user-visible error text

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._allowed_host = ""
        self._allowed_port = -1
        self._allowed_paths: set[str] = set()

    def set_allowed_app_paths(self, host: str, port: int, paths: set[str]) -> None:
        self._allowed_host = host.lower()
        self._allowed_port = port
        self._allowed_paths = set(paths)

    def acceptNavigationRequest(  # noqa: N802
        self,
        url: QUrl | str,
        nav_type: Any,
        is_main_frame: bool,
    ) -> bool:
        qurl = QUrl(url) if isinstance(url, str) else url
        if qurl.scheme().lower() == "about":
            return True
        if _is_allowed_local_url(
            qurl,
            self._allowed_host,
            self._allowed_port,
            self._allowed_paths,
        ):
            return True
        logger.warning(
            "MCPAppWidget: blocked navigation to %s",
            safe_url_for_log(qurl.toString()),
        )
        return False

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
        if lvl >= 2:
            logger.warning("[JS ERR] %s (line %d)", message[:300], line)
            # Skip benign ResizeObserver warnings
            if "ResizeObserver" not in message:
                self.js_error.emit(message[:200])
        elif lvl == 1:
            logger.warning("[JS WARN] %s (line %d)", message[:300], line)
        elif len(message) < 500:
            logger.debug("[JS] %s", message[:200])
