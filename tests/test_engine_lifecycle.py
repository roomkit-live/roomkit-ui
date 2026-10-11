"""Stopping a session that is still connecting stops it — and only once.

stop() during CONNECTING ran the teardown alongside the pending start, which
then resumed: it either resurrected the session (ACTIVE with no transport)
or crashed on the MCP manager the teardown had cleared. Meanwhile a second
start() was accepted and two sessions shared the engine. A failed start set
ERROR before its teardown, so Start, Reset or the wake word could begin
another session while the first was still being released.

The start below runs the real realtime path up to the tool setup, where it
waits the way an MCP server that never answers keeps it waiting.
"""

import asyncio

import pytest

from roomkit_ui.engine import Engine
from roomkit_ui.engine_state import EngineState
from roomkit_ui.toolset import ToolSet

_SETTINGS = {
    "conversation_mode": "realtime",
    "provider": "gemini",
    "api_key": "test-key",
    "aec_mode": "none",
}


def _soon(awaitable):
    """Fail rather than hang when a regression leaves something waiting."""
    return asyncio.wait_for(awaitable, timeout=5)


@pytest.fixture
def engine(qapp, monkeypatch):
    eng = Engine()
    eng.states = []
    eng.errors = []
    eng.state_changed.connect(eng.states.append)
    eng.error_occurred.connect(eng.errors.append)
    eng.tools_reached = asyncio.Event()
    eng.release_tools = asyncio.Event()
    eng.tool_setups = 0

    async def mcp_never_answers(settings):
        eng.tool_setups += 1
        eng.tools_reached.set()
        await eng.release_tools.wait()
        return ToolSet(builtin=[], cli=[], mcp=[])

    monkeypatch.setattr(eng, "_setup_tools", mcp_never_answers)
    yield eng
    if eng._cleanup_monitor_task is not None:
        eng._cleanup_monitor_task.cancel()


async def test_stop_while_connecting_stops_the_start(engine):
    start = asyncio.create_task(engine.start(_SETTINGS))
    await _soon(engine.tools_reached.wait())
    assert engine._transport is not None  # the start has built its transport

    await _soon(engine.stop())

    assert start.done() and start.exception() is None
    assert engine.state == EngineState.IDLE
    assert engine._transport is None
    assert engine.states == [
        EngineState.CONNECTING,
        EngineState.STOPPING,
        EngineState.IDLE,
    ]
    engine.release_tools.set()  # nothing is left waiting to resume
    await asyncio.sleep(0)
    assert engine.state == EngineState.IDLE


async def test_a_second_start_while_connecting_is_refused(engine):
    first = asyncio.create_task(engine.start(_SETTINGS))
    await _soon(engine.tools_reached.wait())

    await _soon(engine.start(_SETTINGS))

    assert engine.tool_setups == 1
    await _soon(engine.stop())
    await _soon(first)


async def test_nothing_starts_while_a_failed_start_is_torn_down(engine, monkeypatch):
    in_cleanup = asyncio.Event()
    finish_cleanup = asyncio.Event()
    real_cleanup = engine._cleanup

    async def slow_cleanup():
        in_cleanup.set()
        await finish_cleanup.wait()
        await real_cleanup()

    monkeypatch.setattr(engine, "_cleanup", slow_cleanup)
    failing = {**_SETTINGS, "api_key": ""}  # the provider refuses to build
    start = asyncio.create_task(engine.start(failing))
    await _soon(in_cleanup.wait())

    assert engine.state == EngineState.STOPPING
    await _soon(engine.start(_SETTINGS))  # Start, the wake word: refused
    await _soon(engine.stop())  # Reset: refused, no second teardown
    assert engine.tool_setups == 0

    finish_cleanup.set()
    await _soon(start)
    assert engine.state == EngineState.ERROR
    assert engine.states[-2:] == [EngineState.STOPPING, EngineState.ERROR]
    assert len(engine.errors) == 1 and "API key" in engine.errors[0]
