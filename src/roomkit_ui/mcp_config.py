"""Helpers for parsing MCP server configuration safely."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse


def parse_mcp_servers(raw: Any) -> list[dict[str, Any]]:
    """Return MCP server dicts from a JSON string/list, ignoring malformed entries."""
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


def is_blank_mcp_server(server: dict[str, Any]) -> bool:
    """An entry "Add server" made and nobody filled in: no name, command or URL."""
    return not any(str(server.get(key) or "").strip() for key in ("name", "command", "url"))


def mcp_server_problem(server: dict[str, Any]) -> str | None:
    """Why this server cannot be started, said for the user; None when it can."""
    if server.get("transport", "stdio") == "stdio":
        return None if str(server.get("command") or "").strip() else "it has no command"
    return None if str(server.get("url") or "").strip() else "it has no URL"


def enabled_mcp_servers(raw: Any) -> list[dict[str, Any]]:
    """Return enabled MCP server configs only, blank entries left out."""
    return [
        server
        for server in parse_mcp_servers(raw)
        if server.get("enabled", True) and not is_blank_mcp_server(server)
    ]


def uses_skills(server: dict[str, Any]) -> bool:
    """Whether the skills this server publishes reach the assistant (on unless
    the user turned them off for it)."""
    return bool(server.get("skills", True))


def has_enabled_mcp_servers(raw: Any) -> bool:
    """Return True if *raw* contains at least one enabled MCP server config."""
    return bool(enabled_mcp_servers(raw))


def validate_mcp_http_url(url: Any) -> str:
    """Return a normalized MCP HTTP URL or raise ValueError for unsafe input."""
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("MCP server URL must use http or https")
    if not parsed.hostname:
        raise ValueError("MCP server URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("MCP server URL must not include credentials")
    return text
