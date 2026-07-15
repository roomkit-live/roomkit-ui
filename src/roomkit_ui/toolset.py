"""Tool composition across the three sources the engine advertises.

Lives in its own leaf module (not engine.py) so the engine mixins can import
it without creating a circular import with Engine — same reason as
``engine_state.py``.

Grouping the sources explicitly replaces the old
``has_mcp_tools = len(tools) > len(BUILTIN_TOOLS)`` inference, which was only
correct while built-ins and MCP were the only two sources.
"""

from __future__ import annotations

from dataclasses import dataclass

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
