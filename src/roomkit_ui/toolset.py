"""Tool composition across the three sources the engine advertises.

Lives in its own leaf module (not engine.py) so the engine mixins can import
it without creating a circular import with Engine — same reason as
``engine_state.py``.

The sources are grouped explicitly rather than inferred from tool counts:
callers need to know *which* source contributed a tool, and no arithmetic on
the combined list can answer that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# session_info truncates for display anyway; this just keeps a seeded --help
# blob (tens of KB) from crossing the Qt signal once per tool.
_SUMMARY_MAX = 200


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
