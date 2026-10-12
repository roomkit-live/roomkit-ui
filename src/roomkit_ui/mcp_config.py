"""Helpers for parsing MCP server configuration safely."""

from __future__ import annotations

import json
import re
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
    if not str(server.get("url") or "").strip():
        return "it has no URL"
    from roomkit_ui.mcp_http_auth import HTTPAuthentication

    return HTTPAuthentication.from_server(server).problem()


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


def uses_instructions(server: dict[str, Any]) -> bool:
    """Whether what this server publishes on using its tools reaches the model
    (on unless the user turned it off for it)."""
    return bool(server.get("instructions", True))


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


# An HTTP header name: RFC 9110's token characters.
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def split_header_line(line: str) -> tuple[str, str] | None:
    """The name and value of a ``Name: value`` line, or None if it is not one.

    The value may be empty: the stored block keeps a secret header as
    ``Name:``, its value in the keyring.  A line pasted from a JSON config
    (``"Authorization": "Bearer …",``) reads the same, quotes and comma off.
    """
    text = line.strip()
    if text.startswith('"'):
        try:
            [(name, value)] = json.loads("{" + text.removesuffix(",") + "}").items()
        except (ValueError, AttributeError):
            return None
        if not isinstance(value, str) or any(c in value for c in "\r\n"):
            return None
    else:
        name, sep, value = text.partition(":")
        if not sep:
            return None
        name, value = name.strip(), value.strip()
    if not _HEADER_NAME.fullmatch(name):
        return None
    return name, value


def header_line(name: str, value: str) -> str:
    """A header as the headers block writes it."""
    return f"{name}: {value}" if value else f"{name}:"


def parse_mcp_headers(raw: Any) -> dict[str, str]:
    """The headers an HTTP server's requests carry, from its ``Name: value`` lines.

    Never raises: a line that is not a header, or has no value, is left out.
    Pair with ``invalid_header_lines`` wherever someone can see the result.
    """
    pairs = (split_header_line(line) for line in str(raw or "").splitlines())
    return {name: value for name, value in (p for p in pairs if p is not None) if value}


def invalid_header_lines(raw: Any) -> int:
    """How many non-blank lines of *raw* ``parse_mcp_headers`` leaves out.

    A count, not the lines: a header line is usually a credential.
    """
    return sum(1 for line in str(raw or "").splitlines() if line.strip() and not _is_sent(line))


def _is_sent(line: str) -> bool:
    pair = split_header_line(line)
    return pair is not None and bool(pair[1])
