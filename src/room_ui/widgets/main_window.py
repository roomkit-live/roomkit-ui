"""Main window assembling all panels and wiring signals."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from room_ui.engine import Engine
from room_ui.settings import load_settings
from room_ui.theme import colors
from room_ui.widgets.chat_view import ChatView
from room_ui.widgets.control_bar import ControlBar
from room_ui.widgets.session_info import SessionInfoBar
from room_ui.widgets.settings_panel import SettingsPanel
from room_ui.widgets.vu_meter import VUMeter

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    settings_saved = Signal()
    session_active_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RoomKit UI")
        self.setFixedWidth(420)
        self.setMinimumHeight(600)
        self.resize(420, 700)

        self._engine = Engine(self)
        c = colors()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Session info bar ──
        self._info_bar = SessionInfoBar()
        root.addWidget(self._info_bar)

        # ── Chat ──
        self._chat = ChatView()
        root.addWidget(self._chat, 1)

        # QWebEngineView is a native widget — when first inserted into the
        # chat, Qt must convert every ancestor to use native window handles.
        # That destroy-and-recreate cycle causes a visible flash across the
        # entire application.  Pre-creating the handles here (before show())
        # means the chain is already native when QWebEngineView appears later.
        from room_ui.widgets.mcp_app_widget import has_webengine

        if has_webengine():
            self._chat.widget().winId()

        # ── VU Meter ──
        self._vu = VUMeter()
        root.addWidget(self._vu)

        # ── Separator ──
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {c['SEPARATOR']};")
        root.addWidget(sep)

        # ── Control bar ──
        self._controls = ControlBar()
        self._controls.setStyleSheet(f"ControlBar {{ background-color: {c['BG_SECONDARY']}; }}")
        root.addWidget(self._controls)

        # ── Signals ──
        self._controls.start_requested.connect(self._on_start)
        self._controls.stop_requested.connect(self._on_stop)
        self._controls.mute_toggled.connect(self._engine.set_mic_muted)
        self._controls.settings_requested.connect(self._open_settings)
        self._controls.reset_requested.connect(self._on_reset)

        self._engine.state_changed.connect(self._on_state_changed)
        self._engine.transcription.connect(self._on_transcription)
        self._engine.mic_audio_level.connect(self._vu.set_mic_level)
        self._engine.speaker_audio_level.connect(self._vu.set_speaker_level)
        self._engine.user_speaking.connect(self._on_user_speaking)
        self._engine.ai_speaking.connect(self._on_ai_speaking)
        self._engine.error_occurred.connect(self._on_error)
        self._engine.tool_use.connect(self._on_tool_use)
        self._engine.tool_use_app.connect(self._on_tool_use_app)
        self._engine.tool_result_app.connect(self._on_tool_result_app)
        self._engine.mcp_status.connect(self._on_mcp_status)
        self._engine.session_info.connect(self._on_session_info)

        # MCP App state
        self._active_app_widgets: dict[str, Any] = {}  # tool_name → MCPAppWidget
        self._pending_app_results: dict[str, str] = {}  # buffered results

    def toggle_session(self) -> None:
        """Toggle the voice session on/off (used by global hotkey)."""
        if self._engine.state in ("active", "connecting"):
            self._on_stop()
        else:
            self._on_start()

    def _open_settings(self) -> None:
        dlg = SettingsPanel(self)
        dlg.exec()
        self.settings_saved.emit()

    def _on_reset(self) -> None:
        if self._engine.state != "idle":
            asyncio.ensure_future(self._engine.stop())
        self._chat.reset()
        self._active_app_widgets.clear()
        self._pending_app_results.clear()

    def _on_start(self) -> None:
        self._chat.clear()
        try:
            asyncio.ensure_future(self._engine.start(load_settings()))
        except Exception as e:
            logger.exception("Failed to schedule engine start")
            self._chat.add_error(str(e))

    def _on_stop(self) -> None:
        try:
            asyncio.ensure_future(self._engine.stop())
        except Exception as e:
            logger.exception("Failed to schedule engine stop")
            self._chat.add_error(str(e))

    def _on_state_changed(self, state: str) -> None:
        self._controls.set_state(state)
        if state == "active":
            self._vu.start()
            self.session_active_changed.emit(True)
        elif state in ("idle", "error"):
            self._vu.stop()
            self._info_bar.clear_session()
            self._active_app_widgets.clear()
            self._pending_app_results.clear()
            self.session_active_changed.emit(False)

    def _on_transcription(self, text: str, role: str, is_final: bool) -> None:
        self._chat.add_transcription(text, role, is_final)

    def _on_user_speaking(self, speaking: bool) -> None:
        if speaking:
            self._chat.show_listening()
        else:
            self._chat.hide_status()

    def _on_ai_speaking(self, speaking: bool) -> None:
        if speaking:
            self._chat.show_thinking()
        else:
            self._chat.hide_status()

    def _on_session_info(self, info: dict) -> None:
        self._info_bar.set_session(info)

    def _on_mcp_status(self, message: str) -> None:
        self._chat.add_info(message)

    def _on_tool_use(self, name: str, arguments: str) -> None:
        logger.info("Tool call: %s(%s)", name, arguments[:200])
        self._chat.add_tool_call(name, arguments)

    def _on_tool_use_app(
        self, name: str, args_json: str, resource_uri: str, server_name: str
    ) -> None:
        logger.info("MCP App tool call: %s (uri=%s)", name, resource_uri)
        asyncio.ensure_future(self._fetch_and_show_app(name, args_json, resource_uri, server_name))

    async def _fetch_and_show_app(
        self, name: str, args_json: str, resource_uri: str, server_name: str
    ) -> None:
        """Fetch HTML from MCP server and embed an app widget in the chat."""
        html: str | None = None
        mcp = self._engine._mcp  # noqa: SLF001
        if mcp is not None:
            html = await mcp.read_resource(name, resource_uri)
        if html:
            # Cache for offline debugging
            import tempfile

            path = os.path.join(tempfile.gettempdir(), f"mcp_app_{name}.html")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.debug("MCP App HTML cached: %s (%d bytes)", path, len(html))
            except Exception:
                pass

        widget = self._chat.add_app_tool_call(name, args_json, html, server_name)
        if widget is None:
            return

        self._active_app_widgets[name] = widget

        # Push tool input to the app
        try:
            arguments = json.loads(args_json)
        except (json.JSONDecodeError, TypeError):
            arguments = {}
        widget.send_tool_input(arguments)

        # Connect app-initiated tool calls
        widget.tool_call_requested.connect(
            lambda rid, tname, targs: self._handle_app_tool_request(rid, tname, targs, name)
        )

        # Check if a result arrived before the widget was ready
        if name in self._pending_app_results:
            widget.send_tool_result(self._pending_app_results.pop(name))

    def _handle_app_tool_request(
        self, request_id: str, tool_name: str, arguments: dict[str, Any], widget_key: str
    ) -> None:
        """Proxy a tools/call from an MCP App through the engine."""
        asyncio.ensure_future(
            self._proxy_app_tool_call(request_id, tool_name, arguments, widget_key)
        )

    async def _proxy_app_tool_call(
        self, request_id: str, tool_name: str, arguments: dict[str, Any], widget_key: str
    ) -> None:
        result = await self._engine.handle_app_tool_call(tool_name, arguments)
        widget = self._active_app_widgets.get(widget_key)
        if widget is not None:
            widget.send_tool_call_response(request_id, result)

    def _on_tool_result_app(self, name: str, result: str) -> None:
        widget = self._active_app_widgets.get(name)
        if widget is not None:
            widget.send_tool_result(result)
        else:
            # Widget not ready yet — buffer the result
            self._pending_app_results[name] = result

    def _on_error(self, msg: str) -> None:
        logger.error("Engine error: %s", msg)
        self._chat.add_error(msg)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._engine.state != "idle":
            asyncio.ensure_future(self._engine.stop())
        super().closeEvent(event)
