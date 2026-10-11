"""Tests for tool grouping across the three sources the engine advertises.

The retry in engine_realtime sheds MCP tools when a provider rejects them, so
``has_mcp`` gates a session restart and ``without_mcp`` is what gets sent on
the second attempt. Both must be exact: a false positive costs a wasted
connect on every failure, and a wrong payload silently drops live tools.
"""

import pytest

from roomkit_ui.builtin_tools import BUILTIN_TOOLS
from roomkit_ui.toolset import ToolSet, reachable_mcp_tools, tool_summaries

BUILTIN = [{"name": "get_current_time", "description": "Get the current local time."}]
CLI = [{"name": "gh", "description": "GitHub CLI"}]
MCP = [{"name": "read_file", "description": "Read a file"}]


def test_all_concatenates_every_source_in_dispatch_order():
    assert ToolSet(builtin=BUILTIN, cli=CLI, mcp=MCP).all == [*BUILTIN, *CLI, *MCP]


def test_without_mcp_keeps_the_hand_authored_sources():
    # Built-in and CLI schemas are ours and known-good; only MCP's are
    # server-supplied, so only MCP gets shed on retry.
    assert ToolSet(builtin=BUILTIN, cli=CLI, mcp=MCP).without_mcp == [*BUILTIN, *CLI]


def test_has_mcp_is_false_when_only_cli_tools_are_declared():
    # This set outnumbers the built-ins without a single MCP tool in it, so
    # has_mcp must read the mcp group and never the combined length: a false
    # positive here fires a retry that sheds tools MCP never contributed.
    toolset = ToolSet(builtin=BUILTIN, cli=CLI, mcp=[])

    assert toolset.has_mcp is False
    assert toolset.all == [*BUILTIN, *CLI]


def test_has_mcp_is_true_only_when_mcp_actually_contributed_tools():
    assert ToolSet(builtin=BUILTIN, cli=[], mcp=MCP).has_mcp is True
    assert ToolSet(builtin=BUILTIN, cli=[], mcp=[]).has_mcp is False


def test_tool_summaries_drop_seeded_help_so_it_never_crosses_the_signal():
    seeded = [{"name": "gh", "description": "GitHub CLI\n\n" + "help " * 10_000}]

    summaries = tool_summaries(seeded)

    assert summaries == [{"name": "gh", "description": "GitHub CLI"}]


def test_tool_summaries_cap_a_long_single_line_description():
    summaries = tool_summaries([{"name": "x", "description": "y" * 500}])

    assert len(summaries[0]["description"]) == 200


def test_tool_summaries_tolerate_missing_keys():
    assert tool_summaries([{}]) == [{"name": "", "description": ""}]


# -- what reaches a roomkit channel ------------------------------------------


def _mcp(name):
    return {
        "type": "function",
        "name": name,
        "description": "",
        "parameters": {"type": "object", "properties": {}},
    }


def test_mcp_tool_named_like_a_builtin_or_cli_tool_is_dropped():
    # mcp-server-time ships get_current_time: dispatch answers it with the
    # built-in, so the MCP one could never run anyway.
    kept, dropped = reachable_mcp_tools(BUILTIN, CLI, [_mcp("get_current_time"), _mcp("gh")])

    assert kept == []
    assert dropped == ["get_current_time", "gh"]


def test_mcp_tool_outside_the_provider_name_rule_is_dropped():
    kept, dropped = reachable_mcp_tools([], [], [_mcp("fs.read"), _mcp("x" * 65), _mcp("ok_1")])

    assert [t["name"] for t in kept] == ["ok_1"]
    assert dropped == ["fs.read", "x" * 65]


def test_channel_options_pin_the_builtins_and_leave_timeouts_to_the_app():
    options = ToolSet(builtin=BUILTIN, cli=CLI, mcp=MCP).channel_options()

    assert options == {"tool_timeout_seconds": None, "tool_search_pinned": ["get_current_time"]}


def test_a_realtime_channel_accepts_the_tools_once_clashes_are_dropped():
    # roomkit refuses a name declared twice when it builds the channel; the
    # engine's retry would then shed every MCP tool, not just the clash.
    from roomkit import RealtimeVoiceChannel
    from roomkit.voice.backends.mock import MockVoiceBackend
    from roomkit.voice.realtime.mock import MockRealtimeProvider

    builtin = list(BUILTIN_TOOLS)
    mcp = [_mcp("get_current_time"), _mcp("read_file")]

    def build(tools, toolset):
        return RealtimeVoiceChannel(
            "voice",
            provider=MockRealtimeProvider(),
            transport=MockVoiceBackend(),
            tools=tools,
            **toolset.channel_options(),
        )

    with pytest.raises(ValueError):
        raw = ToolSet(builtin=builtin, cli=[], mcp=mcp)
        build(raw.all, raw)

    kept, _ = reachable_mcp_tools(builtin, [], mcp)
    toolset = ToolSet(builtin=builtin, cli=[], mcp=kept)
    build(toolset.all, toolset)


def test_an_ai_channel_accepts_the_channel_options():
    from roomkit.channels.ai import AIChannel
    from roomkit.providers.ai.mock import MockAIProvider

    toolset = ToolSet(builtin=list(BUILTIN_TOOLS), cli=[], mcp=[])
    AIChannel("ai", provider=MockAIProvider(responses=["ok"]), **toolset.channel_options())


async def test_the_tools_reach_a_room_whose_binding_carries_none():
    # A background task's room attaches the agent without the metadata it
    # was given in the session's room: the tools must come with the turn.
    from roomkit import ChannelCategory, RoomKit, SMSChannel, TextContent
    from roomkit.channels.ai import AIChannel
    from roomkit.models.delivery import InboundMessage
    from roomkit.providers.ai.mock import MockAIProvider
    from roomkit.providers.sms.mock import MockSMSProvider
    from roomkit.skills import SkillRegistry

    tools = ToolSet(
        builtin=[{"name": "get_current_time", "description": "Time.", "parameters": {}}],
        cli=CLI,
        mcp=[{"name": "activate_skill", "description": "Named like the skills' own."}],
    )
    provider = MockAIProvider(responses=["ok"])
    kit = RoomKit()
    kit.register_channel(
        AIChannel(
            "ai", provider=provider, config_provider=tools.turn_config(), skills=SkillRegistry()
        )
    )
    kit.register_channel(SMSChannel("sms", provider=MockSMSProvider()))
    await kit.create_room(room_id="task")
    await kit.attach_channel("task", "ai", category=ChannelCategory.INTELLIGENCE)
    await kit.attach_channel("task", "sms")

    await kit.process_inbound(
        InboundMessage(channel_id="sms", sender_id="u", content=TextContent(body="hi"))
    )
    await kit.close()

    declared = [t.name for t in provider.calls[0].tools]
    assert {"get_current_time", "gh"} <= set(declared)
    # The host's tool named like the skills' own is left out, where the
    # constructor's tools= would refuse the channel (no skill, none declared).
    assert "activate_skill" not in declared
