"""Stored app output survives navigation/restart, independently of its server."""

import json

import pytest
from PySide6.QtWidgets import QWidget

from roomkit_ui.conversations import Conversation, ConversationStore, _decode_entries
from roomkit_ui.mcp_app_bridge import MCPAppBridge
from roomkit_ui.mcp_app_state import AppToolResults
from roomkit_ui.tool_events import ToolCall, ToolResult
from roomkit_ui.widgets.chat_view import ChatView


@pytest.fixture
def apps(monkeypatch):
    from roomkit_ui.widgets import mcp_app_widget

    created = []

    class App(QWidget):
        def __init__(self, name, server, parent=None):
            super().__init__(parent)
            self.bridge = MCPAppBridge(name, server, self)
            self.messages = []
            self.calls = []
            self.released = False
            self.bridge.messageToApp.connect(lambda msg: self.messages.append(json.loads(msg)))
            self.bridge.tool_call_requested.connect(lambda *args: self.calls.append(args))
            created.append(self)

        def load_html(self, html):
            self.html = html

        def send_tool_input(self, value):
            self.bridge.send_tool_input(value)

        def send_tool_result(self, value):
            self.bridge.send_tool_result(value)

        def set_read_only(self, results=None):
            self.bridge.set_read_only(results)

        def deleteLater(self):  # noqa: N802
            self.released = True
            super().deleteLater()

    monkeypatch.setattr(mcp_app_widget, "MCPAppWidget", App)
    monkeypatch.setattr(mcp_app_widget, "has_webengine", lambda: True)
    return created


def _roll(chat, call_id, total):
    call = ToolCall(call_id, "roll_dice", '{"notation":"1d20"}', "ui://dice", "Dice")
    chat.add_tool_call(call)
    chat.finish_tool_call(ToolResult(call.id, "completed", json.dumps({"total": total})))
    return chat.attach_app(call.id, "<html>Dice app</html>")


@pytest.mark.parametrize("persistent", [True, False])
def test_saved_apps_replay_input_and_own_result_without_calling_tools(qtbot, apps, persistent):
    chat = ChatView()
    qtbot.addWidget(chat)
    first = _roll(chat, "one", 15)
    second = _roll(chat, "two", 4)
    conversation = Conversation(persistent=persistent)
    conversation.update(chat.snapshot())
    store = ConversationStore()
    store.save(conversation)
    if persistent:
        store = ConversationStore()  # A restart, with no live session or MCP server.
    else:
        assert not store.path.exists()
    chat.clear()
    assert first.released and second.released
    chat.restore(store.get(conversation.id).entries)
    assert chat.snapshot() == conversation.entries
    for call_id, total in (("one", 15), ("two", 4)):
        app = chat.tool_call(call_id)._app
        assert app.html == "<html>Dice app</html>"
        bridge = app.bridge
        bridge.receiveMessage(json.dumps({"id": "init", "method": "ui/initialize"}))
        assert "serverTools" in app.messages[-1]["result"]["hostCapabilities"]
        bridge.receiveMessage('{"method":"ui/notifications/initialized"}')
        assert app.messages[-2]["params"] == {"arguments": {"notation": "1d20"}}
        saved = app.messages[-1]["params"]["content"][0]["text"]
        assert json.loads(saved) == {"total": total}
        bridge.receiveMessage(
            '{"id":"roll-again","method":"tools/call","params":{"name":"roll_dice"}}'
        )
        assert app.calls == []
        assert app.messages[-1]["id"] == "roll-again"
        assert app.messages[-1]["result"]["isError"] is True
    chat.clear()
    assert all(app.released for app in apps)


def test_end_session_keeps_app_visible_and_disconnects_its_actions(qtbot, apps):
    chat = ChatView()
    qtbot.addWidget(chat)
    app = _roll(chat, "roll", 15)
    chat.end_session()
    assert chat.tool_call("roll")._app is app and not app.released
    assert chat.snapshot()[0]["app_html"] == app.html
    app.bridge.receiveMessage('{"id":"old","method":"tools/call","params":{}}')
    assert app.calls == [] and app.messages[-1]["result"]["isError"]
    chat.clear()


def test_missing_webengine_keeps_saved_html_for_a_later_reopen(qtbot, apps, monkeypatch):
    chat = ChatView()
    qtbot.addWidget(chat)
    _roll(chat, "roll", 15)
    entries = chat.snapshot()
    monkeypatch.setattr("roomkit_ui.widgets.mcp_app_widget.has_webengine", lambda: False)
    chat.restore(entries)
    assert chat.tool_call("roll")._app is None
    assert chat.tool_call("roll").result.text == '{"total": 15}'
    assert chat.snapshot() == entries
    chat.clear()


def test_older_tool_snapshots_still_open_and_bad_html_is_rejected(qtbot, apps):
    chat = ChatView()
    qtbot.addWidget(chat)
    _roll(chat, "roll", 15)
    entry = chat.snapshot()[0]
    entry.pop("app_html")
    chat.restore(_decode_entries(json.dumps([entry])))
    assert chat.tool_call("roll")._app is None
    assert chat.tool_call("roll").result.status == "completed"
    entry["app_html"] = {"invalid": "type"}
    with pytest.raises(ValueError, match="interface"):
        _decode_entries(json.dumps([entry]))


@pytest.mark.parametrize("persistent", [True, False])
def test_pages_can_read_their_saved_data_after_reopening_without_a_server(qtbot, apps, persistent):
    chat = ChatView()
    qtbot.addWidget(chat)
    _roll(chat, "first", 11)
    _roll(chat, "second", 4)
    for call_id, total in (("first", 11), ("second", 4)):
        responses = chat.tool_call(call_id).app_results
        responses.record("get_screen_data", {"view": "dice"}, '{"result":"{\\"rolls\\":[]}"}')
        responses.record(
            "get_screen_data",
            {"view": "dice"},
            json.dumps({"result": json.dumps({"total": total})}),
        )
        assert len(responses.snapshot()) == 1  # polling updates, not a growing event log
    original = chat.snapshot()
    conversation = Conversation(persistent=persistent)
    conversation.update(original)
    store = ConversationStore()
    store.save(conversation)
    store = ConversationStore() if persistent else store
    chat.restore(store.get(conversation.id).entries)
    for call_id, total in (("first", 11), ("second", 4)):
        app = chat.tool_call(call_id)._app
        for request_id in (30, 31):
            app.bridge.receiveMessage(
                json.dumps(
                    {
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": "get_screen_data", "arguments": {"view": "dice"}},
                    }
                )
            )
            message = app.messages[-1]
            assert message["id"] == str(request_id)
            assert not message["result"]["isError"]
            assert json.loads(message["result"]["content"][0]["text"]) == {"total": total}
        app.bridge.receiveMessage(
            json.dumps(
                {
                    "id": "different-input",
                    "method": "tools/call",
                    "params": {"name": "get_screen_data", "arguments": {"view": "party"}},
                }
            )
        )
        assert app.messages[-1]["result"]["isError"]  # never substitute another view's data
        assert app.calls == []
    assert chat.snapshot() == original
    chat.clear()


def test_app_data_matches_json_input_independently_of_key_order_and_owns_a_copy():
    state = AppToolResults()
    args = {"view": "character", "filter": {"name": "Aria", "level": 4}}
    assert state.record("get_screen_data", args, "saved sheet")
    args["filter"]["name"] = "Other"
    assert state.lookup("get_screen_data", args) is None
    reordered = {"filter": {"level": 4, "name": "Aria"}, "view": "character"}
    assert state.lookup("get_screen_data", reordered) == "saved sheet"
    assert not state.record("get_screen_data", reordered, "saved sheet")
    snapshot = state.snapshot()
    snapshot[0]["arguments"].clear()
    assert state.lookup("get_screen_data", reordered) == "saved sheet"


@pytest.mark.parametrize("invalid", [None, {}, [{"name": "x", "arguments": [], "result": "ok"}]])
def test_damaged_app_responses_are_rejected_before_history_is_replaced(invalid):
    with pytest.raises(ValueError, match="app response"):
        AppToolResults.restore(invalid)
