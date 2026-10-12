"""Tool composition across the three sources the engine advertises.

Lives in its own leaf module (not engine.py) so the engine mixins can import
it without creating a circular import with Engine — same reason as
``engine_state.py``.

The sources are grouped explicitly rather than inferred from tool counts:
callers need to know *which* source contributed a tool, and no arithmetic on
the combined list can answer that.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# session_info truncates for display anyway; this just keeps a seeded --help
# blob (tens of KB) from crossing the Qt signal once per tool.
_SUMMARY_MAX = 200

# The narrowest rule across the providers this app speaks to (CLAUDE.md).
_PROVIDER_TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Tool Search (Settings → Integrations): "auto" lets roomkit decide from the
# thresholds (never with a local model), "on" always hides the catalogue
# behind find_tools, "off" puts every tool in the model's context.  The
# thresholds are roomkit's defaults (channels/_tool_search_constants.py,
# private): 20 tools, Google's 10-20 for Gemini Live; 8000 schema tokens, past
# which hiding the catalogue costs less than re-sending it (RMK-321); 10 % of
# the model's context window.
DEFAULT_TOOL_SEARCH_THRESHOLD = 20
DEFAULT_TOOL_SEARCH_TOKENS = 8000
DEFAULT_TOOL_SEARCH_WINDOW_PCT = 10


@dataclass(frozen=True)
class ToolSet:
    """The tools advertised to a provider, grouped by source."""

    builtin: list[dict]
    cli: list[dict]
    mcp: list[dict]

    @property
    def all(self) -> list[dict]:
        return [*self.builtin, *self.cli, *self.mcp]

    @property
    def without_mcp(self) -> list[dict]:
        """The set to retry with when MCP schemas break a provider's session."""
        return [*self.builtin, *self.cli]

    @property
    def has_mcp(self) -> bool:
        return bool(self.mcp)

    def turn_config(self) -> Callable[[Any, Any], Awaitable[Any]]:
        """An AIChannel ``config_provider`` declaring these tools on every turn.

        Binding metadata reaches only the room it was attached with: a
        background task runs the agent in a room of its own, attached without
        it, where the agent would have no tool at all.  A turn config's tools
        reach every room and are checked as the metadata's are: one named
        like a tool the channel serves itself (skills, Tool Search) is left
        out, where the constructor's ``tools=`` would refuse the channel.
        """
        from roomkit import AIChannelTurnConfig
        from roomkit.providers.ai.base import AITool

        tools = [
            AITool(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("parameters", {}),
            )
            for t in self.all
        ]

        async def provide(_binding: Any, _context: Any) -> Any:
            return AIChannelTurnConfig(tools=list(tools))

        return provide

    def channel_options(self) -> dict[str, Any]:
        """Tool settings for a roomkit channel, so it serves this app's limits.

        roomkit bounds each tool call itself since 0.95 (10 s realtime, 30 s on
        an AIChannel), which would cut an MCP call (60 s here) or a CLI tool's
        own timeout first: the app keeps its bounds, roomkit adds none.  Tool
        Search hides tools behind ``find_tools`` once the catalogue is large;
        the built-ins are what the model calls unprompted (end_conversation,
        set_attitude), so they always stay declared.
        """
        return {
            "tool_timeout_seconds": None,
            "tool_search_pinned": [t["name"] for t in self.builtin],
        }


def tool_search_options(
    settings: dict, *, realtime: bool, local_model: bool = False
) -> dict[str, Any]:
    """A roomkit channel's Tool Search arguments, from Settings → Integrations.

    A realtime channel decides on a tool count, which also caps how many
    tools are live at once.  An AIChannel decides on the schemas' tokens and
    its model's context window; the count only applies when that window is
    unknown.  Automatic leaves a *local_model* every tool: looking one up
    first is a step a small model is less likely to take.  A value that is
    not a positive whole number falls back to roomkit's default.
    """
    mode = settings.get("tool_search_mode", "auto")
    options: dict[str, Any] = {
        "tool_search": {"on": True, "off": False}.get(mode, False if local_model else None),
        "tool_search_threshold": _positive_int(
            settings.get("tool_search_threshold"), DEFAULT_TOOL_SEARCH_THRESHOLD
        ),
    }
    if not realtime:
        options["tool_search_threshold_tokens"] = _positive_int(
            settings.get("tool_search_threshold_tokens"), DEFAULT_TOOL_SEARCH_TOKENS
        )
        pct = _positive_int(settings.get("tool_search_window_pct"), DEFAULT_TOOL_SEARCH_WINDOW_PCT)
        options["tool_search_threshold_pct"] = float(min(pct, 100))
    return options


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def reachable_mcp_tools(
    builtin: list[dict], cli: list[dict], mcp: list[dict]
) -> tuple[list[dict], list[str]]:
    """Split MCP tools into those a provider can be given and the names it cannot.

    Dispatch tries built-ins, then CLI tools, then MCP, so an MCP tool named
    like either never runs.  roomkit also refuses a name declared twice, or
    one outside a provider's rule, when it builds a realtime channel — which
    used to drop every MCP tool through the no-MCP retry.
    """
    taken = {t["name"] for t in (*builtin, *cli)}
    kept: list[dict] = []
    dropped: list[str] = []
    for tool in mcp:
        name = tool.get("name", "")
        if name in taken or not _PROVIDER_TOOL_NAME.fullmatch(name):
            dropped.append(name)
        else:
            kept.append(tool)
    return kept, dropped


def tool_summaries(tools: list[dict]) -> list[dict]:
    """Return ``{name, description}`` per tool for the session_info signal.

    Descriptions collapse to their first line: CLI tools carry seeded
    ``--help`` output in theirs, which the info bar must not try to render.
    """
    return [
        {
            "name": t.get("name", ""),
            "description": _first_line(t.get("description", "")),
        }
        for t in tools
    ]


def _first_line(text: str) -> str:
    line = text.strip().split("\n", 1)[0].strip()
    return line[:_SUMMARY_MAX]
