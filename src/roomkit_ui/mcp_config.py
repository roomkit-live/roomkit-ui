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


def enabled_mcp_servers(raw: Any) -> list[dict[str, Any]]:
    """Return enabled MCP server configs only."""
    return [server for server in parse_mcp_servers(raw) if server.get("enabled", True)]


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
