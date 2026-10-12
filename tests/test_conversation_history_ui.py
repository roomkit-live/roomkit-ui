"""Native history: ending Live keeps a thread, selecting it never starts audio."""

import asyncio
import sqlite3
from unittest.mock import AsyncMock

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QInputDialog

from roomkit_ui.conversations import Conversation, ConversationStore
from roomkit_ui.engine_state import EngineState
from roomkit_ui.theme_live import apply_theme
from roomkit_ui.tool_events import ToolCall, ToolResult
from roomkit_ui.widgets.main_window import MainWindow


def _window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


async def test_hangup_save_restart_select_and_resume_keep_the_same_thread(qtbot, monkeypatch):
    window = _window(qtbot)
    start = AsyncMock()
    monkeypatch.setattr(window._engine, "start", start)
    window._on_start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    first_id = window._history.current.id
    window._engine._state = EngineState.ACTIVE
    window._engine.state_changed.emit(EngineState.ACTIVE)
    window._engine.transcription.emit("Let's plan a walk", "user", True, "")
    window._engine.tool_started.emit(ToolCall("tool-one", "weather", "{}"))
    window._engine.tool_finished.emit(ToolResult("tool-one", "completed", "Sunny"))
    window._engine.transcription.emit("Walk along the canal", "assistant", True, "")
    window._engine._state = EngineState.IDLE
    window._engine.state_changed.emit(EngineState.IDLE)
    assert len(window._chat._bubbles()) == 2
    assert ConversationStore().get(first_id).title == "Let's plan a walk"

    reopened = _window(qtbot)
    resume = AsyncMock()
    monkeypatch.setattr(reopened._engine, "start", resume)
    reopened._history.select(first_id)
    assert len(reopened._chat._bubbles()) == 2
    assert all(b.finalized and not b._stream_timer.isActive() for b in reopened._chat._bubbles())
    assert reopened._chat.tool_call("tool-one").result.text == "Sunny"
    resume.assert_not_called()  # Reading history never opens the microphone.
    reopened._on_start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert resume.call_args.kwargs["conversation_id"] == first_id
    assert "canal" in resume.call_args.kwargs["resume_context"]
    reopened._history.new()
    reopened._on_start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert resume.call_args.kwargs["conversation_id"] != first_id
    assert resume.call_args.kwargs["resume_context"] == ""


def test_drawer_uses_keyboard_search_themes_and_guards_live_navigation(qtbot):
    window = _window(qtbot)
    history = window._history
    for title in ("Trip to Montréal", "Project notes"):
        conversation = Conversation(title=title)
        conversation.update([{"kind": "message", "role": "user", "text": title}])
        history.store.save(conversation)
    QTest.keyClick(window._header._history, Qt.Key_Space)
    qtbot.waitUntil(lambda: history.drawer.pos().x() == 0)
    assert history.drawer.width() == window._surface.width()
    assert not window._controls.isEnabled()
    history.drawer._search.setText("Montréal")
    assert history.drawer._list.count() == 1
    assert "Montréal" in history.drawer._list.item(0).text()
    for theme in ("light", "dark"):
        apply_theme(theme)
        assert history.drawer._search.text() == "Montréal"
    window._engine._state = EngineState.ACTIVE
    history.drawer.set_busy(True)
    history.select(history.drawer._list.item(0).data(Qt.UserRole))
    history.new()
    assert history.current is None
    assert not history.drawer._new.isEnabled()
    QTest.keyClick(history.drawer._close, Qt.Key_Escape)
    qtbot.waitUntil(history.drawer.isHidden)
    assert window._controls.isEnabled()
    window._engine._state = EngineState.IDLE


def test_interrupted_reply_and_speaker_name_survive_history_restore(qtbot):
    window = _window(qtbot)
    window._history.prepare({})
    window._chat.add_transcription("Hello", "user", True, "Alex")
    window._chat.add_transcription("One two three four five six seven", "assistant", False)
    window._on_reply_interrupted(300)
    window._history.save()
    conversation_id = window._history.current.id
    window._history.new()
    window._history.select(conversation_id)
    entries = window._chat.snapshot()
    assert entries[0]["speaker"] == "Alex"
    assert entries[1]["interrupted"]
    assert "seven" not in entries[1]["text"]


def test_a_damaged_archive_keeps_the_open_conversation_intact(qtbot):
    window = _window(qtbot)
    history = window._history
    history.prepare({})
    window._chat.add_transcription("Keep this thread", "user", True)
    history.save()
    current_id = history.current.id
    original = window._chat.snapshot()
    damaged = Conversation(entries=[{"kind": "message", "role": "user", "text": "Old"}])
    history.store.save(damaged)
    connection = sqlite3.connect(history.store.path)
    try:
        with connection:
            connection.execute(
                "UPDATE ui_conversations SET entries=? WHERE id=?",
                ('[{"kind":"message","role":"user","text":42}]', damaged.id),
            )
    finally:
        connection.close()
    history.select(damaged.id)
    history.save()
    assert history.current.id == current_id
    assert window._chat.snapshot() == original
    assert ConversationStore().get(current_id).entries == original
    assert "could not be opened" in history.drawer._notice.text()


async def test_private_thread_stays_private_if_saving_is_later_enabled(qtbot, monkeypatch):
    window = _window(qtbot)
    window._history.prepare({"conversation_memory": False})
    window._chat.add_transcription("Temporary conversation", "user", True)
    window._history.save()
    start = AsyncMock()
    monkeypatch.setattr(window._engine, "start", start)
    # The user's default is on again, but resuming this thread stays private.
    window._on_start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert start.call_args.args[0]["conversation_memory"] is False
    assert not window._history.store.path.exists()


def test_a_late_transcript_cannot_change_the_thread_opened_from_history(qtbot):
    window = _window(qtbot)
    conversation = Conversation(entries=[{"kind": "message", "role": "user", "text": "Saved"}])
    window._history.store.save(conversation)
    window._history.select(conversation.id)
    original = window._chat.snapshot()
    window._engine.transcription.emit("Late old reply", "assistant", True, "")
    assert window._chat.snapshot() == original


def test_history_open_during_live_updates_when_the_call_ends(qtbot):
    window = _window(qtbot)
    history = window._history
    history.prepare({})
    window._engine._state = EngineState.ACTIVE
    window._engine.state_changed.emit(EngineState.ACTIVE)
    history.show()
    assert history.drawer._list.count() == 0
    window._engine.transcription.emit("A new topic", "user", True, "")
    window._engine._state = EngineState.IDLE
    window._engine.state_changed.emit(EngineState.IDLE)
    assert history.drawer._list.count() == 1
    assert "A new topic" in history.drawer._list.item(0).text()
    assert history.drawer._list.isEnabled()


async def test_opening_history_repairs_the_archive_even_with_new_saves_disabled(qtbot):
    from roomkit import RoomKit
    from roomkit.models.event import EventSource, RoomEvent, TextContent

    from roomkit_ui import memory

    window = _window(qtbot)
    kit = RoomKit(store=memory.build_store({}))
    await memory.ensure_room(kit, "main", channels=())
    old = []
    for kind, text in (("channel_attached", "Channel voice attached"), ("message", "Hello")):
        event = await kit.store.add_event_auto_index(
            "main",
            RoomEvent(
                room_id="main",
                type=kind,
                source=EventSource(channel_id="voice", channel_type="voice"),
                content=TextContent(body=text),
            ),
        )
        old.append(
            {"kind": "message", "role": "user", "text": text, "time": event.created_at.isoformat()}
        )
    await kit.close()
    history = window._history
    history.store.save(Conversation(id="main", title="Earlier history", entries=old))
    QSettings().setValue("room/conversation_memory", False)
    history.show()
    assert history.drawer._list.count() == 0
    await asyncio.wait_for(history._import_task, timeout=5)
    assert history.drawer._list.count() == 1
    history.select("main")
    assert [e["text"] for e in window._chat.snapshot()] == ["Hello"]
    assert window._engine.state == EngineState.IDLE


def test_recent_is_limited_to_thirty_and_search_reaches_older_conversations(qtbot):
    from datetime import UTC, datetime, timedelta

    window = _window(qtbot)
    for i in range(35):
        conversation = Conversation(
            title=f"Project {i:02}", entries=[{"kind": "message", "role": "user", "text": str(i)}]
        )
        conversation.updated_at = (
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)
        ).isoformat()
        window._history.store.save(conversation)
    drawer = window._history.drawer
    window._history.show()
    assert drawer._section.text() == "Recent"
    assert drawer._list.count() == 30
    assert drawer._list.item(0).text().startswith("Project 34")
    assert drawer._list.item(29).text().startswith("Project 05")
    drawer._search.setText("Project 00")
    assert drawer._section.text() == "Search results"
    assert drawer._list.count() == 1
    assert drawer._list.item(0).text().startswith("Project 00")
    drawer._search.clear()
    assert drawer._list.count() == 30


def test_settings_live_in_drawer_and_keyboard_rename_keeps_the_thread(qtbot, monkeypatch):
    import roomkit_ui.widgets.conversation_history as history_module
    import roomkit_ui.widgets.main_window as main_module

    window = _window(qtbot)
    history = window._history
    history.prepare({})
    window._chat.add_transcription("Let us plan a weekend", "user", True)
    history.save()
    conversation_id = history.current.id
    old_date = history.current.updated_at
    history.show()
    qtbot.waitUntil(lambda: history.drawer.pos().x() == 0)
    assert not hasattr(window._header, "_settings")
    opened = []

    class Settings(QDialog):
        def exec(self):
            opened.append(True)
            return QDialog.Accepted

    monkeypatch.setattr(main_module, "SettingsPanel", Settings)
    QTest.keyClick(history.drawer._settings, Qt.Key_Space)
    assert opened == [True]
    assert not history.drawer.isHidden()

    class Rename(QInputDialog):
        def exec(self):
            self.setTextValue("Week-end à Montréal")
            return QDialog.Accepted

    monkeypatch.setattr(history_module, "QInputDialog", Rename)
    history.drawer._list.setFocus()
    QTest.keyClick(history.drawer._list, Qt.Key_F2)
    saved = ConversationStore().get(conversation_id)
    assert saved.title == "Week-end à Montréal"
    assert saved.title_source == "manual"
    assert saved.updated_at == old_date
    assert history.current.id == conversation_id
    assert "Week-end" in window._header._title.text()
    history.drawer.set_busy(True)
    assert not history.drawer._settings.isEnabled()


def test_ellipsis_renames_its_row_without_opening_the_conversation(qtbot, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    import roomkit_ui.widgets.conversation_drawer as drawer_module

    window = _window(qtbot)
    history = window._history
    conversation = Conversation(
        title="A saved topic", entries=[{"kind": "message", "role": "user", "text": "Hello"}]
    )
    history.store.save(conversation)
    history.drawer.rename_requested.disconnect(history.rename)
    requested = []
    history.drawer.rename_requested.connect(requested.append)

    class RenameMenu(QMenu):
        def exec(self, *_):
            return self.actions()[0]

    monkeypatch.setattr(drawer_module, "QMenu", RenameMenu)
    history.show()
    qtbot.waitUntil(lambda: history.drawer.pos().x() == 0)
    listing = history.drawer._list
    row = listing.visualItemRect(listing.item(0))
    QTest.mouseClick(
        listing.viewport(), Qt.LeftButton, pos=QPoint(row.right() - 20, row.center().y())
    )
    assert requested == [conversation.id]
    assert history.current is None
    assert not history.drawer.isHidden()


async def test_late_title_keeps_its_thread_and_cannot_overwrite_manual_rename(qtbot, monkeypatch):
    import roomkit_ui.widgets.conversation_history as history_module

    window = _window(qtbot)
    history = window._history
    history.prepare({})
    window._chat.add_transcription("Plan a weekend in Montréal", "user", True)
    window._chat.add_transcription("We can visit the old port", "assistant", True)
    history.save()
    first = history.current.id
    release = asyncio.Event()
    started = asyncio.Event()

    async def generate(transcript, settings):
        assert "Montréal" in transcript
        started.set()
        await release.wait()
        return "Weekend in Montréal"

    monkeypatch.setattr(history_module, "generate_title", generate)
    history.suggest_title()
    history._title_timer.stop()
    history._start_title()
    task = history._title_tasks[first]
    await started.wait()
    history._apply_title(first, "My trip", source="manual")
    history.new()
    history.prepare({})
    window._chat.add_transcription("A completely different topic", "user", True)
    history.save()
    second = history.current.id
    release.set()
    await task
    assert ConversationStore().get(first).title == "My trip"
    assert ConversationStore().get(first).title_source == "manual"
    assert history.current.id == second
    assert history.current.title == "A completely different topic"


async def test_generated_title_stays_in_memory_for_a_private_conversation(qtbot, monkeypatch):
    import roomkit_ui.widgets.conversation_history as history_module

    window = _window(qtbot)
    history = window._history
    history.prepare({"conversation_memory": False})
    window._chat.add_transcription("Plan a weekend in Montréal", "user", True)
    window._chat.add_transcription("Visit the old port", "assistant", True)
    generate = AsyncMock(return_value="Weekend in Montréal")
    monkeypatch.setattr(history_module, "generate_title", generate)
    history.suggest_title()
    history._title_timer.stop()
    history._start_title()
    await history._title_tasks[history.current.id]
    assert history.current.title == "Weekend in Montréal"
    assert history.current.title_source == "generated"
    assert not history.store.path.exists()
    history.suggest_title()
    history._start_title()
    generate.assert_awaited_once()


async def test_deleting_asks_first_then_clears_the_open_thread(qtbot, monkeypatch):
    window = _window(qtbot)
    history = window._history
    other = Conversation(
        title="Another topic", entries=[{"kind": "message", "role": "user", "text": "Hi"}]
    )
    history.store.save(other)
    history.prepare({})
    window._chat.add_transcription("Let us plan a weekend", "user", True)
    history.save()
    conversation_id = history.current.id
    history.show()
    qtbot.waitUntil(lambda: history.drawer.pos().x() == 0)
    asked: list[str] = []
    answer = [False]

    def confirm(title):
        asked.append(title)
        return answer[0]

    monkeypatch.setattr(history, "_confirm_delete", confirm)
    history.drawer._list.setFocus()
    history.drawer._list.setCurrentRow(0)  # the open thread, the most recent
    QTest.keyClick(history.drawer._list, Qt.Key_Delete)
    assert asked == ["Let us plan a weekend"]
    assert ConversationStore().get(conversation_id) is not None  # refused: kept

    answer[0] = True
    QTest.keyClick(history.drawer._list, Qt.Key_Backspace)  # the key macOS calls Delete
    assert history.current is None
    assert window._chat.snapshot() == []
    await asyncio.wait_for(history._delete_task, timeout=5)
    assert ConversationStore().get(conversation_id) is None
    assert history.drawer._list.count() == 1
    assert history.drawer._list.item(0).data(Qt.UserRole) == other.id
    history.save()  # nothing left to save it again
    assert ConversationStore().get(conversation_id) is None


def test_ellipsis_offers_delete_without_opening_the_conversation(qtbot, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    import roomkit_ui.widgets.conversation_drawer as drawer_module

    window = _window(qtbot)
    history = window._history
    conversation = Conversation(
        title="A saved topic", entries=[{"kind": "message", "role": "user", "text": "Hello"}]
    )
    history.store.save(conversation)
    history.drawer.delete_requested.disconnect(history.delete)
    requested = []
    history.drawer.delete_requested.connect(requested.append)

    class DeleteMenu(QMenu):
        def exec(self, *_):
            return self.actions()[1]

    monkeypatch.setattr(drawer_module, "QMenu", DeleteMenu)
    history.show()
    qtbot.waitUntil(lambda: history.drawer.pos().x() == 0)
    listing = history.drawer._list
    row = listing.visualItemRect(listing.item(0))
    QTest.mouseClick(
        listing.viewport(), Qt.LeftButton, pos=QPoint(row.right() - 20, row.center().y())
    )
    assert requested == [conversation.id]
    assert history.current is None


def test_the_delete_question_defaults_to_cancel(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    import roomkit_ui.widgets.conversation_history as history_module

    window = _window(qtbot)
    seen = {}

    class Box(QMessageBox):
        def exec(self):
            seen["default"] = self.defaultButton().text()
            seen["escape"] = self.escapeButton() is self.defaultButton()
            seen["text"] = self.text()
            return 0  # closed without a choice

    monkeypatch.setattr(history_module, "QMessageBox", Box)

    assert window._history._confirm_delete("Weekend") is False
    assert seen == {"default": "Cancel", "escape": True, "text": "Delete “Weekend”?"}
