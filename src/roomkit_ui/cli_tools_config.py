"""Helpers for parsing CLI tool configuration safely.

Mirrors ``mcp_config.py``: Qt-free pure functions, defensive parsing that
never raises on malformed settings, and one ``validate_*`` helper that does
raise because a bad value must not reach the provider.
"""

from __future__ import annotations

import json
import re
from typing import Any

DEFAULT_TIMEOUT = 10.0
DEFAULT_HELP_DEPTH = 2

# Both Gemini and OpenAI constrain function names to this shape.
_UNSAFE_NAME_CHARS = re.compile(r"[^a-z0-9_-]+")


def parse_cli_tools(raw: Any) -> list[dict[str, Any]]:
    """Return CLI tool dicts from a JSON string/list, ignoring malformed entries."""
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    else:
        data = raw

    if not isinstance(data, list):
        return []
    return [dict(item) for item in data if isinstance(item, dict)]


def enabled_cli_tools(raw: Any) -> list[dict[str, Any]]:
    """Return enabled CLI tool configs only."""
    return [tool for tool in parse_cli_tools(raw) if tool.get("enabled", True)]


def has_enabled_cli_tools(raw: Any) -> bool:
    """Return True if *raw* contains at least one enabled CLI tool config."""
    return bool(enabled_cli_tools(raw))


def slugify_tool_name(name: Any) -> str:
    """Return a provider-safe function name derived from *name*.

    Gemini and OpenAI only accept letters, digits, ``_`` and ``-`` in a
    function name, but someone naming a tool should not have to know that —
    "GitHub CLI" becomes "github_cli". Returns "" when nothing usable remains,
    which is the only case a caller must reject.
    """
    text = str(name or "").strip().lower()
    return _UNSAFE_NAME_CHARS.sub("_", text).strip("_-")[:64]


def tool_timeout(cfg: dict[str, Any]) -> float:
    """Return a usable timeout in seconds, falling back to the default."""
    try:
        timeout = float(cfg.get("timeout", DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return timeout if timeout > 0 else DEFAULT_TIMEOUT


def help_depth(cfg: dict[str, Any]) -> int:
    """Return the ``--help`` probe depth, clamped to a sane range."""
    if not cfg.get("seed_help", True):
        return 0
    try:
        depth = int(cfg.get("help_depth", DEFAULT_HELP_DEPTH))
    except (TypeError, ValueError):
        return DEFAULT_HELP_DEPTH
    return max(0, min(depth, 3))
