"""Tests for how Engine assembles and dispatches CLI tools."""

import json

import pytest

from roomkit_ui.engine import Engine

DECL = {"name": "echoer", "command": "echo", "seed_help": False}


@pytest.fixture
def engine(qapp):
    eng = Engine()
    yield eng
    if eng._cleanup_monitor_task is not None:
        eng._cleanup_monitor_task.cancel()


async def test_setup_tools_groups_cli_tools_apart_from_mcp(engine):
    toolset = await engine._setup_tools({"cli_tools": json.dumps([DECL])})

    assert [t["name"] for t in toolset.cli] == ["echoer"]
    assert toolset.mcp == []
    # The bug this guards: a session failure must not fire the MCP retry just
    # because CLI tools made the list longer than the built-ins.
    assert toolset.has_mcp is False
    assert "echoer" in {t["name"] for t in toolset.all}


async def test_setup_tools_without_declarations_leaves_the_manager_unbuilt(engine):
    toolset = await engine._setup_tools({})

    assert toolset.cli == []
    assert engine._cli is None


async def test_setup_tools_skips_a_disabled_declaration(engine):
    toolset = await engine._setup_tools({"cli_tools": json.dumps([{**DECL, "enabled": False}])})

    assert toolset.cli == []


async def test_handle_tool_call_dispatches_to_a_cli_tool(engine):
    await engine._setup_tools({"cli_tools": json.dumps([DECL])})

    out = json.loads(await engine._handle_tool_call("echoer", {"args": ["hi"]}))

    assert out["exit_code"] == 0
    assert out["stdout"].strip() == "hi"


async def test_handle_tool_call_still_prefers_builtins(engine):
    await engine._setup_tools({"cli_tools": json.dumps([DECL])})

    out = json.loads(await engine._handle_tool_call("get_current_time", {}))

    assert "time" in out


async def test_handle_tool_call_brackets_the_watchdog_around_a_cli_call(engine):
    # Without this, a slow CLI call looks like a stalled session.
    await engine._setup_tools({"cli_tools": json.dumps([DECL])})
    seen = []
    engine._watchdog.tool_call_started = lambda: seen.append("start")
    engine._watchdog.tool_call_ended = lambda: seen.append("end")

    await engine._handle_tool_call("echoer", {"args": ["hi"]})

    assert seen == ["start", "end"]
    assert engine._pending_tool_calls == 0


async def test_unknown_tool_is_still_reported_when_cli_tools_exist(engine):
    await engine._setup_tools({"cli_tools": json.dumps([DECL])})

    out = json.loads(await engine._handle_tool_call("nope", {}))

    assert "error" in out


async def test_cleanup_terminates_cli_children_and_clears_the_manager(engine):
    await engine._setup_tools({"cli_tools": json.dumps([DECL])})
    killed = []
    engine._cli.terminate_all = lambda: killed.append(True)

    await engine._cleanup()

    assert killed == [True]
    assert engine._cli is None
