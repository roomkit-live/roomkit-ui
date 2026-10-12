"""Conversation selection, autosave and history navigation for MainWindow."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSettings, QTimer
from PySide6.QtWidgets import QDialog, QInputDialog, QLineEdit
from shiboken6 import isValid

from roomkit_ui.conversation_titles import generate_title, title_transcript
from roomkit_ui.conversations import Conversation, ConversationStore, conversation_context
from roomkit_ui.engine_state import EngineState
from roomkit_ui.widgets.conversation_drawer import ConversationDrawer

if TYPE_CHECKING:
    from roomkit_ui.widgets.main_window import MainWindow

logger = logging.getLogger(__name__)


class ConversationHistory(QObject):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.store = ConversationStore()
        self.current: Conversation | None = None
        self.drawer = ConversationDrawer(window._surface)
        self.drawer.new_requested.connect(self.new)
        self.drawer.selected.connect(self.select)
        self.drawer.rename_requested.connect(self.rename)
        self.drawer.closed.connect(self._closed)
        self._import_task: asyncio.Task | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save)
        self._title_settings: dict = {}
        self._title_tasks: dict[str, asyncio.Task] = {}
        self._title_attempted: set[str] = set()
        self._title_pending: tuple[str, dict] | None = None
        self._title_timer = QTimer(self)
        self._title_timer.setSingleShot(True)
        self._title_timer.timeout.connect(self._start_title)

    @property
    def busy(self) -> bool:
        return self.window._start_pending or self.window._engine.state not in (
            EngineState.IDLE,
            EngineState.ERROR,
        )

    def prepare(self, settings: dict) -> tuple[str, str]:
        if self.current is None:
            self.current = Conversation(persistent=bool(settings.get("conversation_memory", True)))
            self.window._chat.clear()
        else:
            self.current.persistent &= bool(settings.get("conversation_memory", True))
        # A private continuation stays private, including RoomKit's own events.
        settings["conversation_memory"] = self.current.persistent
        self._title_settings = dict(settings)
        self._title_attempted.discard(self.current.id)
        self.window._header.set_conversation(self.current.title)
        return self.current.id, conversation_context(self.current.entries)

    def suggest_title(self, *, ended: bool = False) -> None:
        if self.current is None or self.current.title_source != "fallback":
            return
        self._title_pending = (self.current.id, dict(self._title_settings))
        # The engine does a final FD cleanup 100 ms after hangup. Requests
        # started afterwards keep their sockets until the next owned teardown.
        self._title_timer.start(250 if ended else 1000)

    def _start_title(self) -> None:
        pending, self._title_pending = self._title_pending, None
        if pending is None or self.window._engine.state not in (
            EngineState.ACTIVE,
            EngineState.IDLE,
        ):
            return
        conversation_id, settings = pending
        if conversation_id in self._title_tasks or conversation_id in self._title_attempted:
            return
        try:
            asyncio.get_running_loop()
            self.save()
            conversation = (
                self.current
                if self.current and self.current.id == conversation_id
                else self.store.get(conversation_id)
            )
            if conversation is None or conversation.title_source != "fallback":
                return
            transcript = title_transcript(conversation.entries)
            if not transcript:
                return
            self._title_attempted.add(conversation_id)
            self._title_tasks[conversation_id] = self.window._engine._create_owned_task(
                self._generate_title(conversation_id, transcript, settings),
                name="conversation_title",
            )
        except RuntimeError:
            return  # Synchronous previews have no async loop.
        except Exception:
            logger.exception("Could not prepare a conversation title")

    async def _generate_title(self, conversation_id: str, transcript: str, settings: dict) -> None:
        try:
            title = await generate_title(transcript, settings)
            if title and isValid(self.window):
                self._apply_title(conversation_id, title, source="generated")
        except asyncio.CancelledError:
            self._title_attempted.discard(conversation_id)
            raise
        except Exception:
            logger.exception("Could not save a conversation title")
        finally:
            self._title_tasks.pop(conversation_id, None)

    def _apply_title(self, conversation_id: str, title: str, *, source: str) -> None:
        self.save()
        conversation = (
            self.current
            if self.current and self.current.id == conversation_id
            else self.store.get(conversation_id)
        )
        if conversation is None or (
            source == "generated" and conversation.title_source != "fallback"
        ):
            return
        previous = conversation.title, conversation.title_source
        conversation.rename(title, source=source)
        try:
            self.store.save(conversation)
        except Exception:
            conversation.title, conversation.title_source = previous
            raise
        if self.current and self.current.id == conversation_id:
            self.window._header.set_conversation(conversation.title)
        if not self.drawer.isHidden():
            self._refresh()

    def rename(self, conversation_id: str) -> None:
        if self.busy:
            return
        self.save()
        try:
            conversation = self.store.get(conversation_id)
            if conversation is None:
                return
            dialog = QInputDialog(self.drawer)
            dialog.setWindowTitle("Rename conversation")
            dialog.setLabelText("Conversation title")
            dialog.setTextValue(conversation.title)
            dialog.setOkButtonText("Save")
            field = dialog.findChild(QLineEdit)
            if field is not None:
                field.setMaxLength(80)
                field.selectAll()
            try:
                if dialog.exec() == QDialog.Accepted and dialog.textValue().strip():
                    self._apply_title(conversation_id, dialog.textValue(), source="manual")
            finally:
                dialog.deleteLater()
        except Exception:
            logger.exception("Could not rename the conversation")
            self.drawer.set_notice("The conversation could not be renamed. Please try again.")

    def close(self) -> None:
        self._title_timer.stop()
        self._title_pending = None
        if self.window._engine.state == EngineState.IDLE:
            for task in self._title_tasks.values():
                task.cancel()

    def changed(self) -> None:
        if self.current is not None:
            self._save_timer.start()

    def save(self) -> None:
        self._save_timer.stop()
        if self.current is None:
            return
        entries = self.window._chat.snapshot()
        if entries == self.current.entries:
            return
        self.current.update(entries)
        try:
            self.store.save(self.current)
        except Exception:
            logger.exception("Could not save the conversation")
            self.current.persistent = False
            self.store.save(self.current)
            self.window._chat.add_error(
                "Could not save this conversation. It remains available until the app closes."
            )
        self.window._header.set_conversation(self.current.title)

        if not self.drawer.isHidden():
            self._refresh()

    def show(self) -> None:
        if not self.drawer.isHidden():
            return
        self.save()
        self.drawer.set_busy(self.busy)
        self._refresh()
        self.drawer.present()
        if not QSettings().value("room/conversation_memory", True, type=bool) and not self.busy:
            self.drawer.set_notice("History saving is off. New messages stay in this app session.")
        # Existing saved history can be read/repaired even when new saves are off.
        if self.store.path.exists():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return  # A synchronous widget preview has no qasync loop.
            if self._import_task is None or self._import_task.done():
                self._import_task = loop.create_task(self._import_legacy())

    async def _import_legacy(self) -> None:
        try:
            await self.store.import_legacy()
            if isValid(self.drawer):
                self._refresh()
        except Exception:
            logger.exception("Could not read earlier conversation history")
            if isValid(self.drawer):
                self.drawer.set_notice("Earlier history could not be loaded. Please try again.")

    def _refresh(self) -> None:
        try:
            items = self.store.list()
        except Exception:
            logger.exception("Could not list conversations")
            self.drawer.set_notice(
                "History could not be loaded. Your current conversation is still open."
            )
            return
        self.drawer.set_conversations(items, self.current.id if self.current else "")

    def _closed(self) -> None:
        header = self.window._header if self.window._header.isVisible() else self.window._info_bar
        header._history.setFocus()

    def new(self) -> None:
        if self.busy:
            return
        self.save()
        self.current = None
        self.window._chat.reset()
        self.window._active_app_widgets.clear()
        self.window._header.set_conversation("")
        self.drawer.dismiss()

    def select(self, conversation_id: str) -> None:
        if self.busy:
            return
        self.save()
        try:
            conversation = self.store.get(conversation_id)
            if conversation is None:
                self.drawer.set_notice("This conversation is no longer available.")
                return
            self.window._chat.restore(conversation.entries)
        except Exception:
            logger.exception("Could not restore conversation %s", conversation_id)
            self.drawer.set_notice("This conversation could not be opened.")
            return
        self.current = conversation
        self.window._active_app_widgets.clear()
        self.window._header.set_conversation(conversation.title)
        self.drawer.dismiss()
