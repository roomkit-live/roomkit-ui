"""A failed tool call must raise: since roomkit 0.95, Gemini (text and Live)
reads any returned body as a success, whatever its keys say."""

import asyncio
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
    calls = []
    engine.tool_started.connect(calls.append)
    engine.tool_finished.connect(shown.append)

    with pytest.raises(ToolFailedError, match="timed out"):
        await engine._handle_tool_call("chart", {})

    assert len(shown) == len(calls) == 1
    assert shown[0].call_id == calls[0].id
    assert shown[0].status == "failed"
    assert json.loads(shown[0].text) == {"error": "Tool call timed out after 60s"}
    assert calls[0].resource_uri == "ui://srv/main"
    assert engine._pending_tool_calls == 0


async def test_ordinary_tools_report_the_actual_result(engine):
    calls, results = [], []
    engine.tool_started.connect(calls.append)
    engine.tool_finished.connect(results.append)
    text = await engine._handle_tool_call("get_current_date", {})
    assert len(calls) == len(results) == 1
    assert results[0].call_id == calls[0].id
    assert results[0].status == "completed"
    assert results[0].text == text
    assert "date" in json.loads(text)


async def test_same_tool_can_finish_out_of_order(engine, monkeypatch):
    calls, results = [], []
    engine.tool_started.connect(calls.append)
    engine.tool_finished.connect(results.append)
    release = asyncio.Event()

    async def dispatch(_name, arguments):
        if arguments["number"] == 1:
            await release.wait()
        return json.dumps(arguments)

    monkeypatch.setattr(engine, "_dispatch_tool_call", dispatch)
    first = asyncio.create_task(engine._handle_tool_call("search", {"number": 1}))
    await asyncio.sleep(0)
    await engine._handle_tool_call("search", {"number": 2})
    release.set()
    await first
    assert calls[0].id != calls[1].id
    assert [r.call_id for r in results] == [calls[1].id, calls[0].id]
    assert [json.loads(r.text)["number"] for r in results] == [2, 1]


async def test_cancelled_tool_reports_stopped_and_still_propagates_cancellation(engine):
    class WaitingMCP:
        def get_app_tool_info(self, _name):
            return None

        async def handle_tool_call(self, _name, _arguments):
            await asyncio.Event().wait()

    engine._mcp = WaitingMCP()
    results = []
    engine.tool_finished.connect(results.append)
    task = asyncio.create_task(engine._handle_tool_call("search", {}))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(results) == 1
    assert results[0].status == "cancelled"
    assert engine._pending_tool_calls == 0


async def test_unknown_tool_is_never_shown_as_successful(engine):
    results = []
    engine.tool_finished.connect(results.append)
    assert await engine._handle_tool_call("missing", {}) == '{"error": "Unknown tool"}'
    assert results[0].status == "failed"


async def test_paste_text_without_text_is_a_refusal(engine):
    with pytest.raises(ToolRefusedError):
        await engine._handle_tool_call("paste_text", {"text": ""})


async def test_paste_text_without_its_helper_program_is_a_failure(engine, monkeypatch):
    def missing(_text):
        raise FileNotFoundError(2, "No such file", "xdotool")

    monkeypatch.setattr("roomkit_ui.paste._copy_to_clipboard", missing)

    with pytest.raises(ToolFailedError, match="xdotool"):
        await engine._handle_tool_call("paste_text", {"text": "hello"})
