"""Skills an MCP server publishes (MCP Skills extension, SEP-2640), served through roomkit.

A connected server that declares ``io.modelcontextprotocol/skills`` lists its
skills with ``skills/list``; roomkit's ``SkillRegistry.add_mcp_server`` names
each ``<label>:<path>`` and reads nothing more until the model activates one.
Its ``SKILL.md`` is then read from that server and checked against the
listing (length, SHA-256, frontmatter) before the model sees it, as that
server's data.  The app's part: its own MCP sessions, as roomkit reads a
server (``SessionSkillServer``), a label per server, and what the chat says.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from roomkit.skills.mcp import SKILLS_EXTENSION

from roomkit_ui.cli_tools_config import slugify_tool_name

logger = logging.getLogger(__name__)

# Seconds one request about skills waits: the listing, a SKILL.md, a file.
_REQUEST_TIMEOUT = 10

# Unavailable skills named in the chat at most; the log has them all.
_NAMED_UNAVAILABLE = 5


def declares_skills(session: Any) -> bool:
    """Whether a connected session's server declared the skills extension."""
    capabilities = getattr(session, "server_capabilities", None)
    extensions = getattr(capabilities, "extensions", None)
    return isinstance(extensions, Mapping) and SKILLS_EXTENSION in extensions


class SessionSkillServer:
    """One of the app's MCP sessions, as roomkit's skill registry reads a server.

    roomkit's ``MCPSkillServer``: the extensions the server declared, a
    request the MCP SDK does not model (``skills/list``, ``skills/get``),
    and ``resources/read``.  Its result comes back as the server sent it.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    @property
    def server_extensions(self) -> dict[str, dict[str, Any]]:
        capabilities = getattr(self._session, "server_capabilities", None)
        declared = getattr(capabilities, "extensions", None) or {}
        return {
            str(key): dict(value) for key, value in declared.items() if isinstance(value, dict)
        }

    async def request(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        request = _raw_request(method, dict(params or {}))
        return await asyncio.wait_for(
            self._session.send_request(request, _raw_result()), timeout=_REQUEST_TIMEOUT
        )

    async def read_resource(self, uri: str) -> Any:
        return await asyncio.wait_for(self._session.read_resource(uri), timeout=_REQUEST_TIMEOUT)


def _raw_request(method: str, params: dict[str, Any]) -> Any:
    """A request the SDK does not model: mcp 2.0 sends only its Request types."""
    from mcp import types

    return types.Request[dict[str, Any], str](method=method, params=params)


def _raw_result() -> Any:
    """The result as the server sent it: the SDK's Result would drop its fields."""
    from pydantic import TypeAdapter

    return TypeAdapter(dict[str, Any])


@dataclass(frozen=True)
class SkillServer:
    """A connected server that publishes skills: the app's label for it, the
    name the user gave it, and the server as roomkit reads it."""

    label: str
    name: str
    server: SessionSkillServer


def skill_label(name: str, taken: set[str]) -> str:
    """The label a server's skills are named under (``hugging_face:hf-cli``):
    its name as an identifier, never one another server holds."""
    base = slugify_tool_name(name) or "mcp"
    label, n = base, 2
    while label in taken:
        label = f"{base}_{n}"
        n += 1
    return label


async def add_served_skills(
    registry: Any,
    servers: Sequence[SkillServer],
    *,
    approve_execution: Any,
    execution_tools: Sequence[str],
    notice: Callable[[str], None],
) -> Any:
    """*registry* (a new one when None) with the skills each server publishes.

    A server whose listing fails is said in the chat and left out, the others
    kept.  An entry roomkit does not take (dynamic, past the extension's
    limits) is listed unavailable with its reason: the chat names it.
    *execution_tools* are the app's tools that run code: while one of these
    skills is active, roomkit serves them only once *approve_execution*
    says yes.  Returns None when no skill at all is left.
    """
    if not servers:
        return registry
    from roomkit.skills import SkillError, SkillRegistry

    if registry is None:
        registry = SkillRegistry()
    for served in servers:
        try:
            available = await registry.add_mcp_server(
                served.server,
                served.label,
                approve_execution=approve_execution,
                execution_tools=list(execution_tools),
            )
        except (SkillError, TimeoutError) as exc:
            logger.warning("MCP server %r: skills not read: %s", served.name, exc)
            notice(f"Skills from {served.name} unavailable: they could not be listed.")
            continue
        except Exception:
            # The server's own failure (an MCPError, a dropped session): its tools stay.
            logger.exception("MCP server %r: skills not read", served.name)
            notice(f"Skills from {served.name} unavailable: they could not be listed.")
            continue
        logger.info("MCP server %r: %d skills, as %s:*", served.name, available, served.label)
        _say_unavailable(registry, served, notice)
    return registry if registry.skill_count else None


def _say_unavailable(registry: Any, served: SkillServer, notice: Callable[[str], None]) -> None:
    """Name in the chat the skills of *served* the model will not be offered."""
    prefix = f"{served.label}:"
    unavailable = {
        name: reason
        for name, reason in registry.unavailable_skills.items()
        if name.startswith(prefix)
    }
    if not unavailable:
        return
    for name, reason in unavailable.items():
        logger.info("Skill %s unavailable: %s", name, reason)
    names = sorted(unavailable)
    shown = ", ".join(names[:_NAMED_UNAVAILABLE])
    if len(names) > _NAMED_UNAVAILABLE:
        shown += f" and {len(names) - _NAMED_UNAVAILABLE} more"
    notice(f"Skills from {served.name} not offered (see the log for why): {shown}")
