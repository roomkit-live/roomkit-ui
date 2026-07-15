"""Tests for tool grouping across the three sources the engine advertises.

The retry in engine_realtime sheds MCP tools when a provider rejects them.
It used to decide "MCP tools exist" from ``len(tools) > len(BUILTIN_TOOLS)``,
which turns into a lie the moment a third source contributes tools.
"""

from roomkit_ui.toolset import ToolSet, tool_summaries

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
    # The regression: this set is longer than the built-ins alone, which the
    # old length comparison read as "MCP tools present" — firing a pointless
    # retry that dropped the CLI tools and blamed MCP in the chat.
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
