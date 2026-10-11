"""A failed tool call must raise: since roomkit 0.95, Gemini (text and Live)
reads any returned body as a success, whatever its keys say."""

import json

import pytest
from roomkit import ToolFailedError, ToolRefusedError

from roomkit_ui.engine import Engine


@pytest.fixture
def engine(qapp):
    eng = Engine()
    yield eng
    if eng._cleanup_monitor_task is not None:
        eng._cleanup_monitor_task.cancel()


class _FailingAppMCP:
    """An MCP manager whose one tool is an MCP App tool that fails."""

    def get_app_tool_info(self, name):
        return {"uri": "ui://srv/main", "server": "srv"}

    async def handle_tool_call(self, name, arguments):
        raise ToolFailedError("Tool call timed out after 60s")


async def test_a_failed_mcp_app_tool_raises_and_still_reaches_its_widget(engine):
    engine._mcp = _FailingAppMCP()
    shown = []
    engine.tool_result_app.connect(lambda name, result: shown.append((name, result)))

    with pytest.raises(ToolFailedError, match="timed out"):
        await engine._handle_tool_call("chart", {})

    assert [(n, json.loads(r)) for n, r in shown] == [
        ("chart", {"error": "Tool call timed out after 60s"})
    ]
    assert engine._pending_tool_calls == 0


async def test_paste_text_without_text_is_a_refusal(engine):
    with pytest.raises(ToolRefusedError):
        await engine._handle_tool_call("paste_text", {"text": ""})


async def test_paste_text_without_its_helper_program_is_a_failure(engine, monkeypatch):
    def missing(_text):
        raise FileNotFoundError(2, "No such file", "xdotool")

    monkeypatch.setattr("roomkit_ui.paste._copy_to_clipboard", missing)

    with pytest.raises(ToolFailedError, match="xdotool"):
        await engine._handle_tool_call("paste_text", {"text": "hello"})
