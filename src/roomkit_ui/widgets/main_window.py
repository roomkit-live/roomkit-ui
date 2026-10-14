"""Main window assembling all panels and wiring signals."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QVBoxLayout

from roomkit_ui.call_mode import CallRelay
from roomkit_ui.component_installer import busy_reason
from roomkit_ui.engine import Engine
from roomkit_ui.engine_state import EngineState
from roomkit_ui.idle_hangup import IdleHangup
from roomkit_ui.settings import load_settings
from roomkit_ui.stt_engine import STTEngine
from roomkit_ui.text_chat import image_chat_unavailable, text_chat_unavailable
from roomkit_ui.tool_events import ToolCall, ToolResult
from roomkit_ui.update_check import update_service
from roomkit_ui.widgets.chat_view import ChatView
from roomkit_ui.widgets.composer_dictation import ComposerDictation
from roomkit_ui.widgets.conversation_composer import ConversationComposer
from roomkit_ui.widgets.conversation_history import ConversationHistory
from roomkit_ui.widgets.conversation_home import ConversationHeader, ConversationSurface
from roomkit_ui.widgets.session_drawer import SessionDrawer
from roomkit_ui.widgets.session_info import SessionInfoBar
from roomkit_ui.widgets.session_loading import SessionLoading
from roomkit_ui.widgets.settings import SettingsPanel
from roomkit_ui.widgets.skill_approval_dialog import show_skill_approval
from roomkit_ui.widgets.update_notice import UpdateNotice
from roomkit_ui.widgets.voice_name_dialog import ask_voice_name
from roomkit_ui.widgets.vu_meter import VUMeter

if TYPE_CHECKING:
    from roomkit_ui.widgets.mcp_app_widget import MCPAppWidget

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
        self._stt = STTEngine(self)
        # Join a call: the user's voice in the call, sessions or not, while a call records
        # from RoomKit Microphone; polled, so joining or leaving the call is noticed.
        self._call_relay = CallRelay()
        self._engine.set_call_relay(self._call_relay)
        self._call_relay.apply(load_settings())
        self._call_poll = QTimer(self)
        self._call_poll.setInterval(1000)
        self._call_poll.timeout.connect(self._call_relay.poll)
        self._call_poll.start()

        self._surface = ConversationSurface()
        central = self._surface
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = ConversationHeader()
        root.addWidget(self._header)
        self._update_notice = UpdateNotice(central)  # parented: never a window of its own
        root.addWidget(self._update_notice)

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

        # ── Composer ──
        self._controls = ConversationComposer()
        root.addWidget(self._controls)
        self._start_pending = False
        self._closed = False
        self._request_task: asyncio.Future | None = None
        self._history = ConversationHistory(self)
        self._session_drawer = SessionDrawer(self._surface)
        self._header.history_requested.connect(self._history.show)
        self._info_bar.history_requested.connect(self._history.show)
        self._info_bar.details_requested.connect(self._show_session_details)

        # ── Signals ──
        self._controls.start_requested.connect(self._on_start)
        self._controls.send_requested.connect(self._on_send)
        self._controls.images_shared.connect(self._on_images_shared)
        self._controls.stop_requested.connect(self._on_stop)
        self._controls.mute_toggled.connect(self._engine.set_mic_muted)
        self._controls.mute_toggled.connect(self._vu.set_muted)
        self._controls.call_mute_toggled.connect(self._call_relay.set_muted)
        self._history.drawer.settings_requested.connect(self._open_settings)

        self._engine.state_changed.connect(self._on_state_changed)
        self._engine.state_changed.connect(self._follow_session_for_updates)
        self._engine.transcription.connect(self._on_transcription)
        self._engine.text_reply_stopped.connect(self._chat.stop_text_reply)
        self._engine.mic_audio_level.connect(self._vu.set_mic_level)
        self._engine.speaker_audio_level.connect(self._vu.set_speaker_level)
        self._engine.reply_interrupted.connect(self._on_reply_interrupted)
        self._engine.error_occurred.connect(self._on_error)
        # The engine logged it already, as what it is: a backend not installed.
        self._engine.component_missing.connect(
            lambda feature, _msg: self._chat.add_install_offer(feature)
        )
        self._engine.tool_started.connect(self._on_tool_started)
        self._engine.tool_finished.connect(self._on_tool_finished)
        self._engine.image_generated.connect(self._on_image_generated)
        self._engine.mcp_status.connect(self._on_mcp_status)
        self._engine.session_notice.connect(self._chat.add_info)
        self._engine.loading_status.connect(self._on_loading_status)
        self._engine.session_info.connect(self._on_session_info)
        self._engine.session_cost.connect(self._on_session_cost)
        self._engine.attitude_changed.connect(self._on_attitude_changed)
        self._engine.speaker_named.connect(self._chat.name_voice)
        self._engine.skill_approval_requested.connect(
            lambda approval: show_skill_approval(self, approval)
        )
        self._chat.speaker_clicked.connect(self._ask_voice_name)

        # Closes a session nobody is using — armed from settings, and started
        # only once the session is actually active.
        self._idle_hangup = IdleHangup(self._engine, self)
        self._idle_hangup.hangup.connect(self._on_idle_hangup)
        self._end_notice = ""  # why the session is ending, re-shown once it has
        self._apply_idle_hangup_settings()
        self.settings_saved.connect(self._apply_idle_hangup_settings)
        self.settings_saved.connect(self._refresh_text_availability)
        self._refresh_text_availability()

        # MCP App state
        self._active_app_widgets: dict[str, MCPAppWidget] = {}  # invocation ID → widget
        self._dictation = ComposerDictation(self)

    def toggle_session(self) -> None:
        """Toggle the voice session on/off (used by global hotkey)."""
        if self._engine.state in (EngineState.ACTIVE, EngineState.CONNECTING):
            self._on_stop()
        else:
            self._on_start()

    def _open_settings(self) -> None:
        if self._stt.busy:
            return
        if self._finish_text_session(self._open_settings):
            return
        dlg = SettingsPanel(self)
        self.settings_opened.emit()
        dlg.exec()
        # Built fresh on every open: without this each closed dialog stays
        # alive under the window, its pages, players and models included.
        dlg.deleteLater()
        self._call_relay.apply(load_settings())
        self.settings_saved.emit()

    def _finish_text_session(self, then: Callable[[], None]) -> bool:
        """Close a waiting text session before changing its thread or settings."""
        if self._engine.state != EngineState.READY:
            return False
        self._start_pending = True
        self._history.drawer.set_busy(True)
        task = asyncio.ensure_future(self._engine.stop())
        self._request_task = task

        def finished(done: asyncio.Future) -> None:
            self._start_finished(done)
            if not self._closed and not done.cancelled() and done.exception() is None:
                then()

        task.add_done_callback(finished)
        return True

    def _on_start(self, capture_since: Any = None) -> None:
        if (
            self._stt.busy
            or self._start_pending
            or self._engine.state
            not in (
                EngineState.IDLE,
                EngineState.ERROR,
                EngineState.READY,
            )
        ):
            return  # the engine refuses it: keep the chat of the session ending
        if self._environment_changing():
            return
        settings = load_settings()
        self._history.save()
        conversation_id, context = self._history.prepare(settings)
        self._active_app_widgets.clear()
        try:
            self._start_pending = True
            self._dictation.refresh()
            task = asyncio.ensure_future(
                self._engine.start(
                    settings,
                    capture_since,
                    conversation_id=conversation_id,
                    resume_context=context,
                )
            )
            task.add_done_callback(self._start_finished)
            self._request_task = task
        except Exception as e:
            self._start_pending = False
            logger.exception("Failed to schedule engine start")
            self._chat.add_error(str(e))

    def _environment_changing(self) -> bool:
        """An install or an update is replacing the code a new session would
        run: none starts until it is done, and the chat says why."""
        reason = busy_reason()
        if reason:
            self._chat.add_info(reason)
        return bool(reason)

    def _refresh_text_availability(self) -> None:
        settings = load_settings()
        self._controls.set_text_availability(text_chat_unavailable(settings))
        self._controls.set_image_availability(image_chat_unavailable(settings))

    def _on_send(self, text: str) -> None:
        text = text.strip()
        images = self._controls.images
        if (
            (not text and not images)
            or self._stt.busy
            or self._start_pending
            or self._engine.state not in (EngineState.IDLE, EngineState.ERROR, EngineState.READY)
        ):
            return
        if self._engine.state != EngineState.READY and self._environment_changing():
            return  # the draft stays
        settings = load_settings()
        reason = text_chat_unavailable(settings)
        self._controls.set_text_availability(reason)
        if reason:
            return
        image_reason = image_chat_unavailable(settings)
        self._controls.set_image_availability(image_reason)
        if images and image_reason:
            return
        # Title generation uses this same LLM even if Live uses a realtime provider.
        settings["conversation_mode"] = "voice_channel"
        self._history.save()
        conversation_id, context = self._history.prepare(settings)
        try:
            self._start_pending = True
            self._dictation.refresh()
            task = asyncio.ensure_future(
                self._engine.start(
                    settings,
                    conversation_id=conversation_id,
                    resume_context=context,
                    text=text,
                    images=images,
                    resume_image_entries=self._history.current.entries
                    if self._history.current
                    else [],
                )
            )
            self._request_task = task
            task.add_done_callback(self._start_finished)
        except Exception as exc:
            self._start_pending = False
            logger.exception("Failed to schedule text response")
            self._chat.add_error(str(exc))
            return
        if images:
            self._chat.add_image_message(text, images)
        else:
            self._chat.add_transcription(text, "user", True)
        self._history.changed()
        self._controls.clear_draft()
        self._controls.set_state(EngineState.CONNECTING, text_mode=True)
        self._controls.focus_input()
        self._history.drawer.set_busy(True)
        self._chat.set_text_pending(True)

    def _on_images_shared(self, images: tuple) -> None:
        """Images shared while Live: the user's entry in the chat, and a turn
        of theirs in the session, answered aloud."""
        if self._engine.state != EngineState.ACTIVE or self._engine.is_text:
            return
        self._chat.add_image_message("", images)
        self._history.changed()
        self._engine.share_images(images)

    def _start_finished(self, task: asyncio.Future) -> None:
        self._request_task = None
        self._start_pending = False
        self._dictation.refresh()
        idle = self._engine.state in (EngineState.IDLE, EngineState.ERROR, EngineState.READY)
        self._history.drawer.set_busy(not idle)
        if idle:
            self._controls.set_state(self._engine.state, text_mode=self._engine.is_text)
            self._chat.set_text_pending(False)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Session startup failed: %s", task.exception())

    def start_from_wake_word(self, capture_since: Any) -> None:
        """Open a session because the wake phrase was heard.

        *capture_since* marks where in the shared microphone's backlog the
        utterance began, so what was said before the session existed is
        replayed into it rather than lost to the handshake.
        """
        if self._engine.state not in (EngineState.IDLE, EngineState.ERROR, EngineState.READY):
            return
        self._on_start(capture_since)

    def _on_stop(self) -> None:
        if self._start_pending and self._engine.state in (
            EngineState.IDLE,
            EngineState.ERROR,
            EngineState.READY,
        ):
            if self._request_task is not None:
                self._request_task.cancel()
            return
        try:
            asyncio.ensure_future(
                self._engine.cancel_response() if self._engine.is_text else self._engine.stop()
            )
        except Exception as e:
            logger.exception("Failed to schedule engine stop")
            self._chat.add_error(str(e))

    def _follow_session_for_updates(self, state: str) -> None:
        """No update runs, and none is offered, while a session is open."""
        session_open = state not in (EngineState.IDLE, EngineState.ERROR)
        update_service().set_session_open(session_open)
        self._update_notice.set_session_open(session_open)

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
        self._history.drawer.set_busy(
            state not in (EngineState.IDLE, EngineState.ERROR, EngineState.READY)
        )
        text_mode = self._engine.is_text
        self._controls.set_in_call(
            state == EngineState.ACTIVE
            and not text_mode
            and self._engine.in_call
            and self._call_relay.running
        )
        self._controls.set_state(state, text_mode=text_mode)
        welcome_visible = state in (EngineState.IDLE, EngineState.ERROR)
        self._header.setVisible(welcome_visible)
        if state == EngineState.CONNECTING:
            if not self._engine.text_session_open:
                self._session_drawer.clear_session()
            if text_mode:
                self._header.setVisible(not self._engine.text_session_open)
                self._chat.set_text_pending(True)
                self._conversation_stack.setCurrentWidget(self._chat)
            else:
                self._loading.start()
                self._conversation_stack.setCurrentWidget(self._loading)
        elif state == EngineState.ACTIVE:
            self._conversation_stack.setCurrentWidget(self._chat)
            self._info_bar.show()
            if not text_mode:
                self._controls.set_live_image_availability(self._engine.live_images_unavailable)
                self._vu.show()
                self._vu.start()
                self._idle_hangup.start()
                self.session_active_changed.emit(True)
        elif state == EngineState.READY:
            self._conversation_stack.setCurrentWidget(self._chat)
            self._chat.finish_text_turn()
            self._history.save()
            self._history.suggest_title(ended=True)
            self._info_bar.show()
        elif state in (EngineState.IDLE, EngineState.ERROR):
            self._idle_hangup.stop()
            self._conversation_stack.setCurrentWidget(self._chat)
            has_conversation = bool(self._chat.snapshot())
            self._chat.end_session()
            self._history.save()
            self._history.suggest_title(ended=True)
            if not has_conversation:
                self._chat.reset()
            if self._end_notice and not has_conversation:
                self._chat.add_info(self._end_notice)
            self._end_notice = ""
            self._vu.stop()
            self._vu.hide()
            self._info_bar.hide()
            was_open = not self._session_drawer.isHidden()
            self._session_drawer.clear_session()
            if was_open:
                self._header._history.setFocus()
            self._active_app_widgets.clear()
            if not text_mode:
                self.session_active_changed.emit(False)
        elif state == EngineState.STOPPING:
            self._loading.stop()
            self._vu.stop()

    def _on_transcription(
        self, text: str, role: str, is_final: bool, speaker_name: str = ""
    ) -> None:
        if self._engine.state not in (
            EngineState.ACTIVE,
            EngineState.CONNECTING,
            EngineState.STOPPING,
        ):
            return  # A late provider final must not alter a thread opened from history.
        if self._engine.is_text and role == "assistant":
            self._chat.add_text_reply(text, is_final)
        else:
            self._chat.add_transcription(text, role, is_final, speaker_name)
        self._history.changed()
        if is_final:
            self._history.suggest_title()

    def _on_reply_interrupted(self, heard_ms: int) -> None:
        self._chat.interrupt_reply(heard_ms)
        self._history.changed()

    def _ask_voice_name(self, voice: str) -> None:
        """A click on a voice's name in the chat: ask who it is, tell the engine."""
        from roomkit_ui.speaker_manager import load_speakers

        known = [profile.name for profile in load_speakers()]
        known += [name for name in self._chat.given_names() if name not in known]
        name = ask_voice_name(self, voice, self._chat.voice_name(voice), known)
        if name is not None:
            self._engine.name_speaker(voice, name)

    def _on_session_info(self, info: dict) -> None:
        if self._engine.state in (EngineState.CONNECTING, EngineState.ACTIVE):
            self._session_drawer.set_session(info)

    def _show_session_details(self) -> None:
        if self._engine.state in (EngineState.ACTIVE, EngineState.READY):
            self._session_drawer.present(self._info_bar._details_button)

    def _on_session_cost(self, payload: dict) -> None:
        if self._engine.state in (
            EngineState.CONNECTING,
            EngineState.ACTIVE,
            EngineState.READY,
            EngineState.STOPPING,
        ):
            self._session_drawer.update_cost(payload)

    def _on_attitude_changed(self, description: str) -> None:
        if self._engine.state in (EngineState.CONNECTING, EngineState.ACTIVE, EngineState.READY):
            self._session_drawer.set_attitude(description)

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
        self._history.changed()
        if call.resource_uri:
            self._engine._create_owned_task(
                self._fetch_and_show_app(call),
                name=f"mcp_app_resource_{call.id}",
            )

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
        # HTML may arrive after the reply (and its autosave) completed.
        self._history.changed()
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
        if self._engine.state != EngineState.ACTIVE and not (
            self._engine.text_session_open
            and self._engine.state in (EngineState.READY, EngineState.CONNECTING)
        ):
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
        self._engine._create_owned_task(
            self._proxy_app_tool_call(request_id, tool_name, arguments, widget_key, origin_server),
            name=f"mcp_app_call_{request_id}",
        )

    async def _proxy_app_tool_call(
        self,
        request_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        widget_key: str,
        origin_server: str,
    ) -> None:
        mcp = self._engine._mcp
        widget = self._active_app_widgets.get(widget_key)
        row = self._chat.tool_call(widget_key)
        if self._session_is_over(mcp) or widget is None or row is None:
            return  # A queued request must not run in a replacement session.
        result = await self._engine.handle_app_tool_call(origin_server, tool_name, arguments)
        if (
            self._session_is_over(mcp)
            or self._active_app_widgets.get(widget_key) is not widget
            or self._chat.tool_call(widget_key) is not row
        ):
            return  # Navigation may have replaced this view while its call ran.
        if row.app_results.record(tool_name, arguments, result):
            self._history.changed()
        widget.send_tool_call_response(request_id, result)

    def _on_tool_finished(self, result: ToolResult) -> None:
        row = self._chat.tool_call(result.call_id)
        if row is None or row.result is not None:
            return  # A late result belongs to a cleared session, or is a duplicate.
        self._chat.finish_tool_call(result)
        self._history.changed()
        widget = self._active_app_widgets.get(result.call_id)
        if widget is not None:
            widget.send_tool_result(result.text)

    def _on_image_generated(self, images: tuple) -> None:
        if self._engine.state not in (EngineState.ACTIVE, EngineState.CONNECTING):
            return  # A late drawing must not alter a thread opened from history.
        self._chat.add_assistant_images(images)
        self._history.changed()

    def _on_error(self, msg: str) -> None:
        logger.error("Engine error: %s", msg)
        self._chat.add_error(msg)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closed = True
        self._stt.cancel()
        self._dictation.refresh()
        self._controls._attachments.close_camera()
        self._history.save()
        self._history.close()
        if (
            self._start_pending
            and self._request_task is not None
            and self._engine.state != EngineState.STOPPING
        ):
            self._request_task.cancel()
        if self._engine.state != EngineState.IDLE:
            # Schedule cleanup and give it time to finish before the loop exits.
            # This ensures MCP subprocesses are terminated and audio backends closed.
            task = asyncio.ensure_future(self._engine.stop())
            task.add_done_callback(lambda _: None)  # prevent "task not awaited" warning
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_history"):
            self._history.drawer.resize_to_parent()
        if hasattr(self, "_session_drawer"):
            self._session_drawer.resize_to_parent()
