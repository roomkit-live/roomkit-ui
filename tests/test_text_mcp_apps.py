"""A dice app outlives the AI reply, including when its HTML arrives late."""

import asyncio
import json
import sys

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
from roomkit.providers.ai.base import AIResponse, AIToolCall
from test_engine_text import SETTINGS, TestProvider
from test_engine_text import setup_text as setup_text
from test_text_conversation import configure, until

from roomkit_ui.engine_state import EngineState
from roomkit_ui.toolset import ToolSet
from roomkit_ui.widgets.main_window import MainWindow

DICE = {
    "name": "roll_dice",
    "description": "Roll a die",
    "parameters": {"type": "object", "properties": {}},
}


class DiceMCP:
    failed_servers = []

    def __init__(self, *, delayed=False):
        self.resources = asyncio.Event()
        if not delayed:
            self.resources.set()
        self.closed = 0
        self.app_calls = []

    def get_app_tool_info(self, name):
        return {"uri": "ui://dice", "server": "Dice"} if name == "roll_dice" else None

    async def read_resource(self, *_):
        await self.resources.wait()
        return "<p>12</p>"

    async def handle_tool_call(self, *_):
        assert self.closed == 0
        return '{"total":12}'

    async def handle_app_tool_call(self, server, name, arguments):
        assert not self.closed
        self.app_calls.append((server, name, arguments))
        return '{"total":8}'

    async def close_all(self):
        self.closed += 1


class DiceProvider(TestProvider):
    async def generate(self, context):
        self.contexts.append(context)
        if len(self.contexts) == 1:
            return AIResponse(content="", tool_calls=[AIToolCall(id="roll", name="roll_dice")])
        return AIResponse(content="Le dé donne 12.")


class DiceWidget(QWidget):
    tool_call_requested = Signal(str, str, dict)

    def __init__(self, _name, _server, parent=None):
        super().__init__(parent)
        self.inputs, self.results, self.responses = [], [], []
        self.released = False

    def load_html(self, html):
        self.html = html

    def send_tool_input(self, value):
        self.inputs.append(value)

    def send_tool_result(self, value):
        self.results.append(value)

    def send_tool_call_response(self, *value):
        self.responses.append(value)

    def deleteLater(self):  # noqa: N802
        self.released = True
        super().deleteLater()


@pytest.mark.parametrize("delayed", [False, True])
async def test_app_remains_interactive_between_turns_and_closes_on_new_thread(
    qtbot,
    monkeypatch,
    setup_text,
    delayed,
):
    from roomkit_ui.widgets import mcp_app_widget

    configure(monkeypatch, SETTINGS)
    monkeypatch.setattr(mcp_app_widget, "MCPAppWidget", DiceWidget)
    monkeypatch.setattr(mcp_app_widget, "has_webengine", lambda: True)
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window._history, "suggest_title", lambda **_: None)
    provider = DiceProvider()
    engine = setup_text(provider, window._engine)
    mcp = DiceMCP(delayed=delayed)
    loads = []

    async def tools(*_):
        loads.append(True)
        engine._mcp = mcp
        return ToolSet([], [], [DICE]), None

    monkeypatch.setattr(engine, "_load_vc_tools", tools)
    window._on_send("Lance un dé")
    await window._request_task
    await until(lambda: not window._start_pending)
    assert engine.state == EngineState.READY
    assert not provider.closed and mcp.closed == 0
    mcp.resources.set()  # HTML can arrive after the final assistant token
    await until(lambda: bool(window._active_app_widgets))
    key, widget = next(iter(window._active_app_widgets.items()))
    assert widget.results == ['{"total":12}']
    assert not widget.released
    widget.tool_call_requested.emit("reroll", "roll_dice", {"notation": "1d20"})
    await until(lambda: bool(widget.responses))
    assert widget.responses == [("reroll", '{"total":8}')]
    assert mcp.app_calls == [("Dice", "roll_dice", {"notation": "1d20"})]
    window._on_send("Merci")
    await window._request_task
    await until(lambda: not window._start_pending)
    assert window._active_app_widgets[key] is widget
    assert not widget.released and mcp.closed == 0
    assert loads == [True]  # no reconnect or skill/tool discovery per reply
    window._show_session_details()
    assert not window._session_drawer.isHidden()
    window._session_drawer.dismiss()
    window._history.new()
    await until(lambda: not window._start_pending)
    assert mcp.closed == 1 and provider.closed
    assert widget.released and not window._active_app_widgets
    assert engine._kit is None and engine.state == EngineState.IDLE


async def test_real_stdio_server_survives_followup_and_app_calls(
    setup_text, tmp_path, monkeypatch
):
    from roomkit_ui.engine_vc import VoiceChannelMixin

    server = tmp_path / "dice.py"
    server.write_text("""
import json
import os
from mcp.server.mcpserver import MCPServer
app = MCPServer("dice-test")
rolls = 0
@app.tool()
def roll_dice() -> str:
    global rolls
    rolls += 1
    return json.dumps({"pid": os.getpid(), "rolls": rolls})
app.run("stdio")
""")
    settings = {
        **SETTINGS,
        "mcp_servers": json.dumps(
            [
                {
                    "name": "Dice",
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": str(server),
                    "skills": False,
                }
            ]
        ),
    }
    provider = DiceProvider()
    engine = setup_text(provider)
    monkeypatch.setattr(engine, "_load_vc_tools", VoiceChannelMixin._load_vc_tools.__get__(engine))
    results = []
    engine.tool_finished.connect(results.append)
    await asyncio.wait_for(engine.start(settings, text="Roll", conversation_id="dice"), 10)
    assert engine.state == EngineState.READY
    first = json.loads(json.loads(results[0].text)["result"])
    manager = engine._mcp
    await engine.start(settings, text="Thanks", conversation_id="dice")
    assert engine._mcp is manager
    reroll = json.loads(
        json.loads(await engine.handle_app_tool_call("Dice", "roll_dice", {}))["result"]
    )
    assert reroll["pid"] == first["pid"]
    assert reroll["rolls"] == first["rolls"] + 1
    await asyncio.wait_for(engine.stop(), 5)
    assert engine._mcp is None and provider.closed
