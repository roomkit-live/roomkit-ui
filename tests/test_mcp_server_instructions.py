"""What an MCP server publishes on using its tools reaches the model (roomkit 0.99, RMK-692).

The app keeps each server's instructions from the handshake it negotiated
(``server/discover`` or ``initialize``) and hands them to every channel built
with the servers' tools (``ToolSet.channel_options``).  roomkit adds them to
each system prompt it composes, so the app's own prompt rebuilds (an
attitude, the memory recap) neither drop nor repeat them.
"""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from roomkit import ChannelCategory, RoomKit, SMSChannel, TextContent
from roomkit.models.delivery import InboundMessage
from roomkit.providers.ai.mock import MockAIProvider
from roomkit.providers.sms.mock import MockSMSProvider
from roomkit.voice.realtime.mock import MockRealtimeProvider, MockRealtimeTransport

from roomkit_ui.builtin_tools import BUILTIN_TOOLS
from roomkit_ui.engine import Engine
from roomkit_ui.engine_realtime import _RealtimeMedia
from roomkit_ui.engine_vc import _background_worker_channel
from roomkit_ui.mcp_manager import MCPManager
from roomkit_ui.mcp_skills import skill_label
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.toolset import ToolSet

INSTRUCTIONS = (
    "Resolve every roll yourself: the attack against the target's AC, then the "
    "damage. Never ask the players for a total."
)
HEADING = "## MCP server: game_master"

# A real mcp 2.x server: it answers server/discover, the 2026 protocol.
_MODERN_SERVER = """
import sys

from mcp.server.mcpserver import MCPServer

app = MCPServer("gm", instructions=sys.argv[1] or None)


@app.tool()
def roll(dice: str) -> str:
    return "17"


app.run("stdio")
"""

# A server on the initialize handshake only: server/discover is unknown to it.
_LEGACY_SERVER = """
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    method, request_id = message.get("method"), message.get("id")
    if request_id is None:
        continue
    if method == "initialize":
        result = {
            "protocolVersion": message["params"]["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "legacy-gm", "version": "1"},
            "instructions": sys.argv[1],
        }
    elif method == "tools/list":
        tool = {"name": "roll", "description": "Roll", "inputSchema": {"type": "object"}}
        result = {"tools": [tool]}
    else:
        error = {"code": -32601, "message": "Method not found"}
        print(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": error}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
"""

_ROLL = {
    "type": "function",
    "name": "roll",
    "description": "Roll dice",
    "parameters": {"type": "object", "properties": {"dice": {"type": "string"}}},
}


def _server(tmp_path, source: str, published: str, **cfg) -> dict:
    """A server running *source* that publishes *published* as its instructions."""
    script = tmp_path / "server.py"
    script.write_text(source)
    return {
        "name": "Game Master",
        "transport": "stdio",
        "command": sys.executable,
        "args": f"{script} {json.dumps(published)}",
        **cfg,
    }


async def _connected(*configs: dict) -> MCPManager:
    manager = MCPManager(list(configs))
    await manager.connect_all()
    return manager


def _toolset(instructions: dict[str, str] | None = None) -> ToolSet:
    return ToolSet(
        builtin=[dict(tool) for tool in BUILTIN_TOOLS],
        cli=[],
        mcp=[dict(_ROLL)],
        instructions={"game_master": INSTRUCTIONS} if instructions is None else instructions,
    )


def _once(prompt: str | None) -> bool:
    """The instructions are in *prompt*, exactly once."""
    text = prompt or ""
    return text.count(INSTRUCTIONS) == 1 and text.count(HEADING) == 1


# -- the manager: what each server published ---------------------------------------------


@pytest.mark.parametrize(
    "source", [_MODERN_SERVER, _LEGACY_SERVER], ids=["discover", "initialize"]
)
async def test_the_negotiated_handshake_carries_the_instructions(tmp_path, source):
    manager = await _connected(_server(tmp_path, source, INSTRUCTIONS))
    try:
        session = manager._tool_to_session["roll"]
        # Read from the handshake the session actually settled on.
        assert (session.discover_result is not None) is (source is _MODERN_SERVER)
        assert manager.instructions() == {"game_master": INSTRUCTIONS}
    finally:
        await asyncio.wait_for(manager.close_all(), timeout=5)
    assert manager.instructions() == {}


async def test_a_server_that_publishes_none_adds_nothing(tmp_path):
    manager = await _connected(_server(tmp_path, _MODERN_SERVER, ""))
    try:
        assert [t["name"] for t in manager.get_tools()] == ["roll"]
        assert manager.instructions() == {}
    finally:
        await asyncio.wait_for(manager.close_all(), timeout=5)


async def test_turned_off_its_instructions_stay_out_and_its_tools_stay_in(tmp_path):
    manager = await _connected(_server(tmp_path, _MODERN_SERVER, INSTRUCTIONS, instructions=False))
    try:
        assert [t["name"] for t in manager.get_tools()] == ["roll"]
        assert manager.instructions() == {}
    finally:
        await asyncio.wait_for(manager.close_all(), timeout=5)


def test_a_server_connected_again_replaces_what_it_said():
    manager = MCPManager([])
    cfg = {"id": "gm-1", "name": "Game Master"}

    manager._keep_instructions(cfg, SimpleNamespace(instructions="Old rules."), "Game Master")
    manager._keep_instructions(cfg, SimpleNamespace(instructions=INSTRUCTIONS), "Game Master")
    assert manager.instructions() == {"game_master": INSTRUCTIONS}

    manager._keep_instructions(cfg, SimpleNamespace(instructions=None), "Game Master")
    assert manager.instructions() == {}


def test_two_servers_of_one_name_keep_their_own():
    manager = MCPManager([])
    manager._keep_instructions(
        {"id": "a", "name": "Docs"}, SimpleNamespace(instructions="A."), "Docs"
    )
    manager._keep_instructions(
        {"id": "b", "name": "Docs"}, SimpleNamespace(instructions="B."), "Docs"
    )

    assert manager.instructions() == {"docs": "A.", "docs_2": "B."}


def test_a_label_stays_one_roomkit_takes():
    long_name = "x" * 80
    first = skill_label(long_name, set())
    second = skill_label(long_name, {first})

    assert len(first) == 64 and len(second) == 64
    assert second.endswith("_2") and second != first


async def test_the_session_toolset_carries_them(tmp_path, qapp):
    engine = Engine()
    settings = {
        **_DEFAULTS,
        "mcp_servers": json.dumps([_server(tmp_path, _MODERN_SERVER, INSTRUCTIONS)]),
    }
    try:
        toolset = await engine._setup_tools(settings)
        assert toolset.instructions == {"game_master": INSTRUCTIONS}
        assert toolset.channel_options()["server_instructions"] == {"game_master": INSTRUCTIONS}
    finally:
        await asyncio.wait_for(engine._mcp.close_all(), timeout=5)


# -- the Voice Channel ----------------------------------------------------------------------


async def _vc_channel(engine: Engine, settings: dict, toolset: ToolSet, provider) -> object:
    async def tools(_settings, _provider):
        return toolset, None

    engine._load_vc_tools = tools
    prompt = engine._compose_session_prompt(settings)
    channel, _, _ = await engine._build_vc_ai_channel(settings, provider, "anthropic", prompt)
    engine._ai_channel = channel
    return channel


async def _room_with(channel) -> RoomKit:
    kit = RoomKit()
    kit.register_channel(channel)
    kit.register_channel(SMSChannel("sms", provider=MockSMSProvider()))
    await kit.create_room(room_id="room")
    await kit.attach_channel("room", channel.channel_id, category=ChannelCategory.INTELLIGENCE)
    await kit.attach_channel("room", "sms")
    return kit


async def _say(kit: RoomKit, text: str) -> None:
    await kit.process_inbound(
        InboundMessage(channel_id="sms", sender_id="u", content=TextContent(body=text))
    )


async def test_every_voice_channel_turn_carries_them_once_through_the_prompt_rebuilds(qapp):
    engine = Engine()
    provider = MockAIProvider(responses=["ok", "ok", "ok"])
    settings = {**_DEFAULTS, "system_prompt": "You are the game master."}
    channel = await _vc_channel(engine, settings, _toolset(), provider)
    kit = await _room_with(channel)
    try:
        await _say(kit, "I attack the goblin.")
        # The memory recap, then an attitude: the app sets its prompt again.
        engine._memory_recap = "Earlier: the party reached the inn."
        await engine._apply_attitude("calm", "Speak calmly.")
        await _say(kit, "I cast a fireball.")
    finally:
        await kit.close()

    first, second = provider.calls[0].system_prompt, provider.calls[1].system_prompt
    assert _once(first) and _once(second)
    assert "Earlier: the party reached the inn." in second and "Speak calmly." in second
    # After the app's prompt, as roomkit places them.
    assert second.index("Speak calmly.") < second.index(HEADING)


async def test_tool_search_leaves_them_in_the_prompt(qapp):
    engine = Engine()
    provider = MockAIProvider(responses=["ok"])
    settings = {**_DEFAULTS, "tool_search_mode": "on"}
    channel = await _vc_channel(engine, settings, _toolset(), provider)
    kit = await _room_with(channel)
    try:
        await _say(kit, "I attack the goblin.")
    finally:
        await kit.close()

    context = provider.calls[0]
    declared = [tool.name for tool in context.tools]
    assert "find_tools" in declared and "roll" not in declared  # the catalogue is hidden
    assert _once(context.system_prompt)


@pytest.mark.parametrize("instructions", [{}, None], ids=["none-published", "turned-off"])
async def test_without_instructions_the_prompt_has_no_section(qapp, instructions):
    engine = Engine()
    provider = MockAIProvider(responses=["ok"])
    channel = await _vc_channel(engine, dict(_DEFAULTS), _toolset(instructions or {}), provider)
    kit = await _room_with(channel)
    try:
        await _say(kit, "Hello.")
    finally:
        await kit.close()

    assert "MCP server" not in provider.calls[0].system_prompt


async def test_the_background_worker_reads_them_too(qapp):
    engine = Engine()
    provider = MockAIProvider(responses=["done"])
    agent = SimpleNamespace(worker=provider, worker_provider="anthropic")
    channel = _background_worker_channel(dict(_DEFAULTS), agent, "Work.", _toolset(), None, engine)
    kit = await _room_with(channel)
    try:
        await _say(kit, "Roll for initiative.")
    finally:
        await kit.close()

    assert _once(provider.calls[0].system_prompt)


# -- typed turns ----------------------------------------------------------------------------


async def test_a_typed_turn_carries_them_once(qapp, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr("roomkit_ui.text_chat.is_available", lambda _: True)
    monkeypatch.setattr(Engine, "_finalize_event_loop", AsyncMock())
    monkeypatch.setattr(Engine, "_load_vc_tools", AsyncMock(return_value=(_toolset(), None)))
    provider = MockAIProvider(responses=["The goblin falls."])
    monkeypatch.setattr("roomkit_ui.engine_text.create_ai_provider", lambda *_, **__: provider)
    engine = Engine()
    settings = {
        **_DEFAULTS,
        "vc_llm_provider": "anthropic",
        "anthropic_api_key": "test-only",
        "conversation_memory": False,
    }
    try:
        await asyncio.wait_for(engine.start(settings, text="I attack.", conversation_id="t"), 5)
    finally:
        await engine.stop()

    context = provider.calls[0]
    assert _once(context.system_prompt)
    # The voice-only hangup is left out; the instructions are not.
    assert "end_conversation" not in [tool.name for tool in context.tools]


# -- realtime -------------------------------------------------------------------------------


class _Provider(MockRealtimeProvider):
    """Refuses the session while it declares an MCP tool, when *refuse_mcp*."""

    def __init__(self, refuse_mcp: bool) -> None:
        super().__init__()
        self._refuse_mcp = refuse_mcp

    async def connect(self, session, *, tools=None, **kwargs):
        if self._refuse_mcp and any(t["name"] == "roll" for t in tools or []):
            raise ValueError("invalid tool schema")
        await super().connect(session, tools=tools, **kwargs)

    def prompts(self) -> list[str]:
        return [call.args["system_prompt"] for call in self.calls if call.method == "connect"]


def _media_builder(refuse_mcp: bool = False):
    built: list[_RealtimeMedia] = []

    def build() -> _RealtimeMedia:
        media = _RealtimeMedia(
            provider=_Provider(refuse_mcp),
            voice="Aoede",
            model="mock",
            transport=MockRealtimeTransport(),
            pipeline=None,
            aec=None,
            sample_rate=24000,
        )
        built.append(media)
        return media

    return build, built


async def _realtime(engine: Engine, build, settings: dict) -> None:
    prompt = engine._compose_session_prompt(settings)
    await engine._open_realtime_session(
        build(), build, prompt, _toolset(), settings=settings, provider_config=None, skills=None
    )


async def test_a_realtime_session_carries_them_through_an_attitude_change(qapp):
    engine = Engine()
    build, built = _media_builder()
    settings = {**_DEFAULTS, "conversation_memory": False, "system_prompt": "You are the GM."}
    try:
        await _realtime(engine, build, settings)
        await engine._apply_attitude("calm", "Speak calmly.")
        prompts = built[0].provider.prompts()
    finally:
        await engine._cleanup()

    # Connected, then reconfigured (reconnected) with the attitude.
    assert len(prompts) == 2
    assert all(_once(prompt) for prompt in prompts)
    assert "Speak calmly." in prompts[1]


async def test_a_realtime_session_with_tool_search_keeps_them(qapp):
    engine = Engine()
    build, built = _media_builder()
    settings = {**_DEFAULTS, "conversation_memory": False, "tool_search_mode": "on"}
    try:
        await _realtime(engine, build, settings)
        assert engine._channel._tool_search_support is not None
        (prompt,) = built[0].provider.prompts()
    finally:
        await engine._cleanup()

    assert _once(prompt)


async def test_the_retry_without_mcp_drops_them_with_the_tools(qapp):
    engine = Engine()
    build, built = _media_builder(refuse_mcp=True)
    settings = {**_DEFAULTS, "conversation_memory": False}
    try:
        await _realtime(engine, build, settings)
        (prompt,) = built[-1].provider.prompts()
    finally:
        await engine._cleanup()

    assert len(built) == 2  # refused with MCP, then started without it
    assert INSTRUCTIONS not in prompt and "MCP server" not in prompt


# -- settings -------------------------------------------------------------------------------


def test_the_switch_is_on_by_default_and_saved_in_the_server_entry(qapp):
    import shiboken6

    from roomkit_ui.settings import load_settings, save_settings
    from roomkit_ui.widgets.settings.mcp_page import _MCPPage

    # An entry saved before the switch existed reads as on.
    older = {"id": "gm-1", "name": "Game Master", "command": "gamemaster-mcp"}
    page = _MCPPage({**_DEFAULTS, "mcp_servers": json.dumps([older])})
    try:
        page._show_edit(0)
        assert page._instructions_check.isChecked()
        page._instructions_check.setChecked(False)
        page._add_server()
        page._name_edit.setText("Docs")
        assert page._instructions_check.isChecked()
        save_settings(page.get_settings())
    finally:
        shiboken6.delete(page)

    saved = json.loads(load_settings()["mcp_servers"])
    assert [server["instructions"] for server in saved] == [False, True]
