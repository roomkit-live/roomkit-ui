"""Main window assembling all panels and wiring signals."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from roomkit_ui.engine import Engine
from roomkit_ui.engine_state import EngineState
from roomkit_ui.idle_hangup import IdleHangup
from roomkit_ui.settings import load_settings
from roomkit_ui.theme_live import themed_style
from roomkit_ui.widgets.chat_view import ChatView
from roomkit_ui.widgets.control_bar import ControlBar
from roomkit_ui.widgets.loading_overlay import LoadingOverlay
from roomkit_ui.widgets.session_info import SessionInfoBar
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
        self.resize(420, 700)

        self._engine = Engine(self)

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
        from roomkit_ui.widgets.mcp_app_widget import has_webengine

        if has_webengine():
            w = self._chat.widget()
            if w is not None:
                w.winId()

        # ── VU Meter ──
        self._vu = VUMeter()
        root.addWidget(self._vu)

        # Full-window curtain while a session connects (child of the central
        # widget so it covers everything, chat and controls included).
        self._loading_overlay = LoadingOverlay(central)

        # ── Separator ──
        sep = QWidget()
        sep.setFixedHeight(1)
        themed_style(sep, lambda c: f"background-color: {c['SEPARATOR']};")
        root.addWidget(sep)

        # ── Control bar ──
        self._controls = ControlBar()
        themed_style(
            self._controls, lambda c: f"ControlBar {{ background-color: {c['BG_SECONDARY']}; }}"
        )
        root.addWidget(self._controls)

        # ── Signals ──
        self._controls.start_requested.connect(self._on_start)
        self._controls.stop_requested.connect(self._on_stop)
        self._loading_overlay.cancel_requested.connect(self._on_stop)
        self._controls.mute_toggled.connect(self._engine.set_mic_muted)
        self._controls.settings_requested.connect(self._open_settings)
        self._controls.reset_requested.connect(self._on_reset)

        self._engine.state_changed.connect(self._on_state_changed)
        self._engine.transcription.connect(self._on_transcription)
        self._engine.mic_audio_level.connect(self._vu.set_mic_level)
        self._engine.speaker_audio_level.connect(self._vu.set_speaker_level)
        self._engine.user_speaking.connect(self._on_user_speaking)
        self._engine.ai_speaking.connect(self._on_ai_speaking)
        self._engine.reply_interrupted.connect(self._chat.interrupt_reply)
        self._engine.error_occurred.connect(self._on_error)
        # The engine logged it already, as what it is: a backend not installed.
        self._engine.component_missing.connect(
            lambda feature, _msg: self._chat.add_install_offer(feature)
        )
        self._engine.tool_use.connect(self._on_tool_use)
        self._engine.tool_use_app.connect(self._on_tool_use_app)
        self._engine.tool_result_app.connect(self._on_tool_result_app)
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
        self._active_app_widgets: dict[str, Any] = {}  # tool_name → MCPAppWidget
        self._pending_app_results: dict[str, str] = {}  # buffered results

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

    def _on_reset(self) -> None:
        if self._engine.state != EngineState.IDLE:
            asyncio.ensure_future(self._engine.stop())
        self._chat.reset()
        for widget in self._active_app_widgets.values():
            widget.deleteLater()
        self._active_app_widgets.clear()
        self._pending_app_results.clear()

    def _on_start(self, capture_since: Any = None) -> None:
        if self._engine.state not in (EngineState.IDLE, EngineState.ERROR):
            return  # the engine refuses it: keep the chat of the session ending
        self._chat.clear()
        # clear() deleted every app widget along with the rest of the chat.
        self._active_app_widgets.clear()
        self._pending_app_results.clear()
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
        if state == EngineState.CONNECTING:
            self._loading_overlay.set_status("Starting session…")
            self._loading_overlay.show_loading()
        elif state == EngineState.ACTIVE:
            self._chat.clear_loading_status()
            self._loading_overlay.dismiss()
            self._vu.start()
            self._idle_hangup.start()
            self.session_active_changed.emit(True)
        elif state in (EngineState.IDLE, EngineState.ERROR):
            self._idle_hangup.stop()
            self._loading_overlay.dismiss()
            self._chat.reset()
            if self._end_notice:
                self._chat.add_info(self._end_notice)
                self._end_notice = ""
            self._vu.stop()
            self._info_bar.clear_session()
            for widget in self._active_app_widgets.values():
                widget.deleteLater()
            self._active_app_widgets.clear()
            self._pending_app_results.clear()
            self.session_active_changed.emit(False)

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

    def _on_loading_status(self, message: str) -> None:
        # The full-window overlay narrates startup; the chat stays clean.
        self._loading_overlay.set_status(message)

    def _on_tool_use(self, name: str, arguments: str) -> None:
        logger.info("Tool call: %s (%d arg chars)", name, len(arguments))
        logger.debug("Tool call arguments for %s: %s", name, arguments)
        self._chat.add_tool_call(name, arguments)

    def _on_tool_use_app(
        self, name: str, args_json: str, resource_uri: str, server_name: str
    ) -> None:
        logger.info("MCP App tool call: %s (server=%s)", name, server_name)
        logger.debug("MCP App resource for %s: %s", name, resource_uri)
        asyncio.ensure_future(self._fetch_and_show_app(name, args_json, resource_uri, server_name))

    async def _fetch_and_show_app(
        self, name: str, args_json: str, resource_uri: str, server_name: str
    ) -> None:
        """Fetch HTML from MCP server and embed an app widget in the chat."""
        html: str | None = None
        mcp = self._engine._mcp  # noqa: SLF001
        if mcp is not None:
            html = await mcp.read_resource(name, resource_uri)
            if self._session_is_over(mcp):
                return  # the chat it belonged to is gone
        if html and os.environ.get("DEBUG"):
            # Cache for offline debugging
            import tempfile

            safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
            path = os.path.join(tempfile.gettempdir(), f"mcp_app_{safe_name}.html")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.debug("MCP App HTML cached: %s (%d bytes)", path, len(html))
            except Exception:
                logger.debug("MCP App HTML cache write failed: %s", path, exc_info=True)

        widget = self._chat.add_app_tool_call(name, args_json, html, server_name)
        if widget is None:
            return

        # Clean up any existing widget for the same tool name to prevent leaks
        if name in self._active_app_widgets:
            old = self._active_app_widgets.pop(name)
            try:
                old.deleteLater()
            except Exception:
                logger.debug("deleteLater failed for stale app widget %s", name, exc_info=True)
        self._active_app_widgets[name] = widget

        # Push tool input to the app
        try:
            arguments = json.loads(args_json)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Malformed tool arguments for %s, sending empty input", name)
            arguments = {}
        widget.send_tool_input(arguments)

        # Connect app-initiated tool calls
        widget.tool_call_requested.connect(
            lambda rid, tname, targs: self._handle_app_tool_request(
                rid,
                tname,
                targs,
                name,
                server_name,
            )
        )

        # Check if a result arrived before the widget was ready
        if name in self._pending_app_results:
            widget.send_tool_result(self._pending_app_results.pop(name))

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
        result = await self._engine.handle_app_tool_call(origin_server, tool_name, arguments)
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
        if self._engine.state != EngineState.IDLE:
            # Schedule cleanup and give it time to finish before the loop exits.
            # This ensures MCP subprocesses are terminated and audio backends closed.
            task = asyncio.ensure_future(self._engine.stop())
            task.add_done_callback(lambda _: None)  # prevent "task not awaited" warning
        super().closeEvent(event)
