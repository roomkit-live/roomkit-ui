"""Python-side bridge for the MCP Apps JSON-RPC protocol.

Exposed to JavaScript via QWebChannel. The JS shim intercepts
``window.parent.postMessage`` calls from the MCP App and forwards them
here; responses travel back via the ``messageToApp`` signal which the
shim dispatches as a ``MessageEvent`` on ``window``.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import webbrowser
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)

_PROTOCOL_VERSION = "2026-01-26"


def _to_call_tool_result(result: Any) -> dict[str, Any]:
    """Normalise a tool result into the MCP ``CallToolResult`` shape.

    Accepts a raw JSON string, a dict that already has ``content``, or any
    other value and wraps it into ``{"content": [...], "isError": false}``.
    """
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            parsed = result
    else:
        parsed = result

    # Already in CallToolResult shape
    if isinstance(parsed, dict) and "content" in parsed and isinstance(parsed["content"], list):
        return parsed

    # Our handle_tool_call returns {"result": text} or {"error": text}
    if isinstance(parsed, dict):
        if "error" in parsed:
            text = str(parsed["error"])
            return {"content": [{"type": "text", "text": text}], "isError": True}
        if "result" in parsed:
            text = str(parsed["result"])
            return {"content": [{"type": "text", "text": text}], "isError": False}

    # Wrap a plain value into a text content block
    text = parsed if isinstance(parsed, str) else json.dumps(parsed)
    return {"content": [{"type": "text", "text": text}], "isError": False}


class MCPAppBridge(QObject):
    """Bidirectional bridge between an MCP App (JS) and the host (Python)."""

    # Python → JS (shim listens on this signal)
    messageToApp = Signal(str)  # noqa: N815

    # App requested a tool call: (request_id, tool_name, arguments)
    tool_call_requested = Signal(str, str, dict)

    # App reported a size change: (width, height)
    size_changed = Signal(int, int)

    # App requested a display mode change: (mode)
    display_mode_requested = Signal(str)

    def __init__(
        self,
        tool_name: str,
        server_name: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool_name = tool_name
        self._server_name = server_name
        self._initialized = False
        self._pending: list[str] = []  # queued JSON messages until app is ready

    # -- JS → Python ----------------------------------------------------------

    @Slot(str)
    def receiveMessage(self, json_str: str) -> None:  # noqa: N802
        """Called by the JS shim when the app sends ``postMessage``."""
        try:
            msg = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            logger.warning("MCPAppBridge: invalid JSON from app: %s", json_str[:200])
            return

        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "ui/initialize":
            self._handle_initialize(msg_id)
        elif method == "tools/call":
            self._handle_tools_call(msg_id, params)
        elif method == "ui/open-link":
            self._handle_open_link(params)
        elif method == "ui/request-display-mode":
            self._handle_display_mode(msg_id, params)
        elif method == "ui/notifications/size-changed":
            self._handle_size_changed(params)
        elif method == "ui/notifications/initialized":
            self._initialized = True
            logger.debug("MCPAppBridge: app initialized (%s)", self._tool_name)
            self._flush_pending()
        elif method.startswith("notifications/"):
            logger.debug("MCPAppBridge: notification %r", method)
        else:
            logger.debug("MCPAppBridge: unhandled method %r", method)

    # -- Python → JS convenience ----------------------------------------------

    def send_tool_input(self, arguments: dict[str, Any]) -> None:
        """Push tool-call arguments to the app (``ui/notifications/tool-input``)."""
        self._send_notification("ui/notifications/tool-input", {"arguments": arguments})

    def send_tool_result(self, result: Any) -> None:
        """Push tool-call result to the app (``ui/notifications/tool-result``).

        ``result`` may be a raw string (from the MCP tool call) or a dict.
        We normalise it into the ``CallToolResult`` shape that MCP Apps expect:
        ``{"content": [{"type": "text", "text": "..."}]}``.
        """
        call_tool_result = _to_call_tool_result(result)
        self._send_notification("ui/notifications/tool-result", call_tool_result)

    def send_tool_call_response(self, request_id: str, result: str) -> None:
        """Return a ``tools/call`` response to the app."""
        call_tool_result = _to_call_tool_result(result)
        resp = {"jsonrpc": "2.0", "id": request_id, "result": call_tool_result}
        self.messageToApp.emit(json.dumps(resp))

    def notify_host_context_changed(self, **kwargs: Any) -> None:
        """Notify the app of host context changes (e.g. display mode)."""
        self._send_notification("ui/notifications/host-context-changed", kwargs)

    # -- protocol handlers ----------------------------------------------------

    def _handle_initialize(self, msg_id: str | None) -> None:
        resp: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": _PROTOCOL_VERSION,
                "hostCapabilities": {
                    "serverTools": {},
                    "openLinks": {},
                },
                "hostInfo": {"name": "RoomKit UI", "version": "0.1"},
                "hostContext": {
                    "toolInfo": {
                        "tool": {
                            "name": self._tool_name,
                            "inputSchema": {"type": "object"},
                        },
                    },
                    "theme": "dark",
                    "displayMode": "inline",
                    "availableDisplayModes": ["inline", "fullscreen"],
                    "platform": "desktop",
                },
            },
        }
        self.messageToApp.emit(json.dumps(resp))

    def _handle_tools_call(self, msg_id: str | None, params: dict[str, Any]) -> None:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        request_id = str(msg_id) if msg_id is not None else ""
        self.tool_call_requested.emit(request_id, tool_name, arguments)

    @staticmethod
    def _handle_open_link(params: dict[str, Any]) -> None:
        url = params.get("uri") or params.get("url", "")
        if not url:
            return
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning("MCPAppBridge: blocked open_link scheme %r: %s", parsed.scheme, url)
            return
        webbrowser.open(url)

    def _handle_display_mode(self, msg_id: str | None, params: dict[str, Any]) -> None:
        mode = params.get("mode", "inline")
        logger.debug("MCPAppBridge: display mode request → %s", mode)
        # Acknowledge the request (app waits for this response)
        resp: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"mode": mode},
        }
        self.messageToApp.emit(json.dumps(resp))
        self.display_mode_requested.emit(mode)

    def _handle_size_changed(self, params: dict[str, Any]) -> None:
        width = int(params.get("width", 0))
        height = int(params.get("height", 0))
        if width > 0 and height > 0:
            self.size_changed.emit(width, height)

    # -- helpers --------------------------------------------------------------

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        msg_json = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        if self._initialized:
            self.messageToApp.emit(msg_json)
        else:
            self._pending.append(msg_json)
            logger.debug("MCPAppBridge: queued %s (app not ready)", method)

    def _flush_pending(self) -> None:
        """Send all queued messages now that the app is initialized."""
        pending = self._pending
        self._pending = []
        for msg_json in pending:
            self.messageToApp.emit(msg_json)
