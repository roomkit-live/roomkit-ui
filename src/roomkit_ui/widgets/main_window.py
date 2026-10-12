"""Main window assembling all panels and wiring signals."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QVBoxLayout

from roomkit_ui.engine import Engine
from roomkit_ui.engine_state import EngineState
from roomkit_ui.idle_hangup import IdleHangup
from roomkit_ui.settings import load_settings
from roomkit_ui.tool_events import ToolCall, ToolResult
from roomkit_ui.widgets.chat_view import ChatView
from roomkit_ui.widgets.conversation_composer import ConversationComposer
from roomkit_ui.widgets.conversation_home import ConversationHeader, ConversationSurface
from roomkit_ui.widgets.session_info import SessionInfoBar
from roomkit_ui.widgets.session_loading import SessionLoading
from roomkit_ui.widgets.settings import SettingsPanel
from roomkit_ui.widgets.voice_name_dialog import ask_voice_name
from roomkit_ui.widgets.vu_meter import VUMeter

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    settings_saved = Signal()
    settings_opened = Signal()  # paired with settings_saved, emitted on close
    session_active_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RoomKit UI")
        self.setFixedWidth(420)
        self.setMinimumHeight(600)
        self.resize(420, 740)

        self._engine = Engine(self)

        self._surface = ConversationSurface()
        central = self._surface
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = ConversationHeader()
        root.addWidget(self._header)

        # ── Session info bar ──
        self._info_bar = SessionInfoBar()
        root.addWidget(self._info_bar)

        # ── Chat ──
        self._chat = ChatView()
        self._loading = SessionLoading()
        self._conversation_stack = QStackedWidget()
        self._conversation_stack.setStyleSheet("background: transparent;")
        self._conversation_stack.addWidget(self._chat)
        self._conversation_stack.addWidget(self._loading)
        root.addWidget(self._conversation_stack, 1)
        # No native handle anywhere in the chat: Qt 6's QWebEngineView renders
        # through a QQuickWidget, which stops rendering correctly once it or
        # an ancestor has one (QTBUG-40765).  The chat container was made
        # native here for Qt 5's native web view; on macOS that left MCP Apps
        # in native child views inside the scroll area, and the conversation
        # area showed blank or a shifted copy of the window mid-session.

        # ── VU Meter ──
        self._vu = VUMeter()
        self._vu.hide()  # audio feedback only occupies space during Live
        root.addWidget(self._vu)

        # ── Composer (Live first; text input follows in a later step) ──
        self._controls = ConversationComposer()
        root.addWidget(self._controls)

        # ── Signals ──
        self._controls.start_requested.connect(self._on_start)
        self._controls.stop_requested.connect(self._on_stop)
        self._controls.mute_toggled.connect(self._engine.set_mic_muted)
        self._controls.mute_toggled.connect(self._vu.set_muted)
        self._header.settings_requested.connect(self._open_settings)

        self._engine.state_changed.connect(self._on_state_changed)
        self._engine.transcription.connect(self._on_transcription)
        self._engine.mic_audio_level.connect(self._vu.set_mic_level)
        self._engine.speaker_audio_level.connect(self._vu.set_speaker_level)
        self._engine.reply_interrupted.connect(self._chat.interrupt_reply)
        self._engine.error_occurred.connect(self._on_error)
        # The engine logged it already, as what it is: a backend not installed.
        self._engine.component_missing.connect(
            lambda feature, _msg: self._chat.add_install_offer(feature)
        )
        self._engine.tool_started.connect(self._on_tool_started)
        self._engine.tool_finished.connect(self._on_tool_finished)
        self._engine.mcp_status.connect(self._on_mcp_status)
        self._engine.session_notice.connect(self._chat.add_info)
        self._engine.loading_status.connect(self._on_loading_status)
        self._engine.session_info.connect(self._on_session_info)
        self._engine.session_cost.connect(self._info_bar.update_cost)
        self._engine.attitude_changed.connect(self._info_bar.set_attitude)
        self._engine.speaker_named.connect(self._chat.name_voice)
        self._chat.speaker_clicked.connect(self._ask_voice_name)

        # Closes a session nobody is using — armed from settings, and started
        # only once the session is actually active.
        self._idle_hangup = IdleHangup(self._engine, self)
        self._idle_hangup.hangup.connect(self._on_idle_hangup)
        self._end_notice = ""  # why the session is ending, re-shown once it has
        self._apply_idle_hangup_settings()
        self.settings_saved.connect(self._apply_idle_hangup_settings)

        # MCP App state
        self._active_app_widgets: dict[str, Any] = {}  # invocation ID → MCPAppWidget

    def toggle_session(self) -> None:
        """Toggle the voice session on/off (used by global hotkey)."""
        if self._engine.state in (EngineState.ACTIVE, EngineState.CONNECTING):
            self._on_stop()
        else:
            self._on_start()

    def _open_settings(self) -> None:
        dlg = SettingsPanel(self)
        self.settings_opened.emit()
        dlg.exec()
        # Built fresh on every open: without this each closed dialog stays
        # alive under the window, its pages, players and models included.
        dlg.deleteLater()
        self.settings_saved.emit()

    def _on_start(self, capture_since: Any = None) -> None:
        if self._engine.state not in (EngineState.IDLE, EngineState.ERROR):
            return  # the engine refuses it: keep the chat of the session ending
        self._chat.clear()
        # clear() deleted every app widget along with the rest of the chat.
        self._active_app_widgets.clear()
        try:
            asyncio.ensure_future(self._engine.start(load_settings(), capture_since))
        except Exception as e:
            logger.exception("Failed to schedule engine start")
            self._chat.add_error(str(e))

    def start_from_wake_word(self, capture_since: Any) -> None:
        """Open a session because the wake phrase was heard.

        *capture_since* marks where in the shared microphone's backlog the
        utterance began, so what was said before the session existed is
        replayed into it rather than lost to the handshake.
        """
        if self._engine.state not in (EngineState.IDLE, EngineState.ERROR):
            return
        self._on_start(capture_since)

    def _on_stop(self) -> None:
        try:
            asyncio.ensure_future(self._engine.stop())
        except Exception as e:
            logger.exception("Failed to schedule engine stop")
            self._chat.add_error(str(e))

    def _apply_idle_hangup_settings(self) -> None:
        settings = load_settings()
        self._idle_hangup.configure(
            enabled=bool(settings.get("idle_hangup_enabled", False)),
            delay_seconds=float(settings.get("idle_hangup_seconds", 15) or 15),
        )

    def _on_idle_hangup(self, reason: str) -> None:
        # Say why the session closed — a call that ends by itself with no
        # explanation reads as a crash.  Shown now, while the session winds
        # down, and again once the IDLE transition has reset the chat.
        self._chat.add_info(reason)
        self._end_notice = reason
        self._on_stop()

    def _on_state_changed(self, state: str) -> None:
        self._controls.set_state(state)
        welcome_visible = state in (EngineState.IDLE, EngineState.ERROR)
        self._header.setVisible(welcome_visible)
        if state == EngineState.CONNECTING:
            self._loading.start()
            self._conversation_stack.setCurrentWidget(self._loading)
        elif state == EngineState.ACTIVE:
            self._conversation_stack.setCurrentWidget(self._chat)
            self._info_bar.show()
            self._vu.show()
            self._vu.start()
            self._idle_hangup.start()
            self.session_active_changed.emit(True)
        elif state in (EngineState.IDLE, EngineState.ERROR):
            self._idle_hangup.stop()
            self._conversation_stack.setCurrentWidget(self._chat)
            self._chat.reset()
            if self._end_notice:
                self._chat.add_info(self._end_notice)
                self._end_notice = ""
            self._vu.stop()
            self._vu.hide()
            self._info_bar.clear_session()
            self._active_app_widgets.clear()
            self.session_active_changed.emit(False)
        elif state == EngineState.STOPPING:
            self._loading.stop()
            self._vu.stop()

    def _on_transcription(
        self, text: str, role: str, is_final: bool, speaker_name: str = ""
    ) -> None:
        self._chat.add_transcription(text, role, is_final, speaker_name)

    def _ask_voice_name(self, voice: str) -> None:
        """A click on a voice's name in the chat: ask who it is, tell the engine."""
        from roomkit_ui.speaker_manager import load_speakers

        known = [profile.name for profile in load_speakers()]
        known += [name for name in self._chat.given_names() if name not in known]
        name = ask_voice_name(self, voice, self._chat.voice_name(voice), known)
        if name is not None:
            self._engine.name_speaker(voice, name)

    def _on_session_info(self, info: dict) -> None:
        self._info_bar.set_session(info)

    def _on_mcp_status(self, message: str) -> None:
        self._chat.add_info(message)

    def _on_loading_status(self, message: str) -> None:
        logger.info("Session startup: %s", message)
        self._loading.set_status(message)

    def _on_tool_started(self, call: ToolCall) -> None:
        if self._engine.state not in (EngineState.ACTIVE, EngineState.CONNECTING):
            return
        logger.info("Tool call: %s (%d arg chars)", call.name, len(call.arguments_json))
        self._chat.add_tool_call(call)
        if call.resource_uri:
            asyncio.ensure_future(self._fetch_and_show_app(call))

    async def _fetch_and_show_app(self, call: ToolCall) -> None:
        """Fetch HTML from MCP server and embed an app widget in the chat."""
        html: str | None = None
        mcp = self._engine._mcp  # noqa: SLF001
        if mcp is not None:
            try:
                html = await mcp.read_resource(call.name, call.resource_uri)
            except Exception:
                logger.warning(
                    "Could not load interactive output for %s", call.name, exc_info=True
                )
                return  # Keep the ordinary tool row and its result available.
            if self._session_is_over(mcp):
                return  # the chat it belonged to is gone
        row = self._chat.tool_call(call.id)
        if row is None:
            return
        if html and os.environ.get("DEBUG"):
            # Cache for offline debugging
            import tempfile

            safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in call.name)
            path = os.path.join(tempfile.gettempdir(), f"mcp_app_{safe_name}.html")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.debug("MCP App HTML cached: %s (%d bytes)", path, len(html))
            except Exception:
                logger.debug("MCP App HTML cache write failed: %s", path, exc_info=True)

        widget = self._chat.attach_app(call.id, html)
        if widget is None:
            return

        self._active_app_widgets[call.id] = widget

        # Push tool input to the app
        try:
            arguments = json.loads(call.arguments_json)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Malformed tool arguments for %s, sending empty input", call.name)
            arguments = {}
        widget.send_tool_input(arguments)

        # Connect app-initiated tool calls
        widget.tool_call_requested.connect(
            lambda rid, tname, targs: self._handle_app_tool_request(
                rid,
                tname,
                targs,
                call.id,
                call.server_name,
            )
        )

        # Check if a result arrived before the widget was ready
        if row.result is not None:
            widget.send_tool_result(row.result.text)

    def _session_is_over(self, mcp: Any) -> bool:
        """Whether the session that owned *mcp* has ended (or been replaced).

        Each session builds its own MCP manager, so a different one means a
        new session started while the caller was awaiting.
        """
        if self._engine.state != EngineState.ACTIVE:
            return True
        return self._engine._mcp is not mcp  # noqa: SLF001

    def _handle_app_tool_request(
        self,
        request_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        widget_key: str,
        origin_server: str,
    ) -> None:
        """Proxy a tools/call from an MCP App through the engine."""
        asyncio.ensure_future(
            self._proxy_app_tool_call(request_id, tool_name, arguments, widget_key, origin_server)
        )

    async def _proxy_app_tool_call(
        self,
        request_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        widget_key: str,
        origin_server: str,
    ) -> None:
        if self._engine.state != EngineState.ACTIVE or widget_key not in self._active_app_widgets:
            return  # A queued request must not run in a replacement session.
        result = await self._engine.handle_app_tool_call(origin_server, tool_name, arguments)
        widget = self._active_app_widgets.get(widget_key)
        if widget is not None:
            widget.send_tool_call_response(request_id, result)

    def _on_tool_finished(self, result: ToolResult) -> None:
        row = self._chat.tool_call(result.call_id)
        if row is None or row.result is not None:
            return  # A late result belongs to a cleared session, or is a duplicate.
        self._chat.finish_tool_call(result)
        widget = self._active_app_widgets.get(result.call_id)
        if widget is not None:
            widget.send_tool_result(result.text)

    def _on_error(self, msg: str) -> None:
        logger.error("Engine error: %s", msg)
        self._chat.add_error(msg)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._engine.state != EngineState.IDLE:
            # Schedule cleanup and give it time to finish before the loop exits.
            # This ensures MCP subprocesses are terminated and audio backends closed.
            task = asyncio.ensure_future(self._engine.stop())
            task.add_done_callback(lambda _: None)  # prevent "task not awaited" warning
        super().closeEvent(event)
