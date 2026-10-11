"""MCP (Model Context Protocol) client manager.

Connects to configured MCP servers, collects their tools, and routes
tool calls from the voice assistant to the correct server.

Each server's MCP context managers live inside their own long-running
asyncio Task so that anyio cancel-scopes are entered and exited in the
same task (required by anyio, which MCP uses internally) — and so the
servers can connect in parallel instead of one slow server stalling
session start for everyone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import sys
from contextlib import AsyncExitStack
from typing import Any

from roomkit_ui.cli_exec import resolve_command, search_path
from roomkit_ui.env_config import parse_env_block
from roomkit_ui.mcp_config import mcp_server_problem, validate_mcp_http_url

_CONNECT_TIMEOUT = 10  # seconds per connection step, per server
_MAX_TOOL_PAGES = 1000  # a server paging on past this is not listing anything
_TOOL_CALL_TIMEOUT = 60  # seconds per tool call

# JSON Schema keys that voice providers (especially Gemini) reject.
_STRIP_SCHEMA_KEYS = {"$schema", "additionalProperties"}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scoped unraisable-hook install
# ---------------------------------------------------------------------------
#
# When an MCP task is cancelled, the streamable_http_client async generator
# may be finalized by GC in a different task context, triggering an anyio
# "Attempted to exit cancel scope in a different task" RuntimeError.  This
# is harmless but very noisy.  We install a hook to suppress it, but do so
# only while an MCPManager is active — touching ``sys.unraisablehook`` at
# module import time would silently affect every other library in the
# process (tests, pyinstaller bootstrap, etc.).

_hook_install_count = 0
_previous_unraisable_hook: Any = None


def _anyio_cancel_scope_hook(unraisable: sys.UnraisableHookArgs) -> None:
    exc = unraisable.exc_value
    if isinstance(exc, RuntimeError) and "cancel scope" in str(exc):
        logger.debug("Suppressed anyio cancel-scope error during cleanup: %s", exc)
        return
    prev = _previous_unraisable_hook or sys.__unraisablehook__
    prev(unraisable)


def _install_unraisable_hook() -> None:
    """Install the anyio-cancel-scope suppressor.  Idempotent, refcounted."""
    global _hook_install_count, _previous_unraisable_hook
    if _hook_install_count == 0:
        _previous_unraisable_hook = sys.unraisablehook
        sys.unraisablehook = _anyio_cancel_scope_hook
    _hook_install_count += 1


def _uninstall_unraisable_hook() -> None:
    """Restore whatever hook was in place before ``_install_unraisable_hook``."""
    global _hook_install_count, _previous_unraisable_hook
    if _hook_install_count == 0:
        return
    _hook_install_count -= 1
    if _hook_install_count == 0:
        # Only restore if nothing else has replaced us — don't stomp on a
        # later installer.
        if sys.unraisablehook is _anyio_cancel_scope_hook:
            sys.unraisablehook = _previous_unraisable_hook or sys.__unraisablehook__
        _previous_unraisable_hook = None


def _clean_schema(obj: Any) -> Any:
    """Recursively strip JSON Schema keys that voice providers reject."""
    if isinstance(obj, dict):
        return {k: _clean_schema(v) for k, v in obj.items() if k not in _STRIP_SCHEMA_KEYS}
    if isinstance(obj, list):
        return [_clean_schema(v) for v in obj]
    return obj


async def _list_all_tools(session: Any, name: str) -> list[Any]:
    """Every page of a server's ``tools/list``.

    The SDK answers one page; a server that pages its listing would lose
    every tool after the first.  A server that pages on without bringing
    anything new (an empty page that still carries a cursor, a cursor handed
    out twice), or past ``_MAX_TOOL_PAGES``, ends the reading with the tools
    read so far.
    """
    from mcp.types import PaginatedRequestParams

    tools: list[Any] = []
    seen: set[str] = set()
    cursor: str | None = None
    for _ in range(_MAX_TOOL_PAGES):
        params = PaginatedRequestParams(cursor=cursor) if cursor is not None else None
        page = await session.list_tools(params=params)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if cursor is None:
            return tools
        if not page.tools or cursor in seen:
            logger.warning(
                "MCP server %r pages its tools without end; keeping %d", name, len(tools)
            )
            return tools
        seen.add(cursor)
    logger.warning(
        "MCP server %r: tool listing past %d pages; keeping %d", name, _MAX_TOOL_PAGES, len(tools)
    )
    return tools


def _parse_stdio_config(cfg: dict[str, Any]) -> tuple[str, list[str], dict[str, str]]:
    """Parse a stdio server config into (command, args, env).

    shlex honours quoting, so executables with spaces in their path
    (e.g. ``"/Applications/My App/server"``) parse as one token.

    A macOS .app launched from the Dock inherits only
    ``/usr/bin:/bin:/usr/sbin:/sbin``, and the MCP SDK passes that PATH on:
    ``npx``/``uvx`` were not found, nor was ``node`` for a script starting
    ``#!/usr/bin/env node``. The command is resolved on ``search_path()``
    and the child gets that PATH too, unless the server declares its own.
    The SDK merges *env* over a handful of inherited variables (HOME, USER…),
    never the whole environment, so no PyInstaller library path leaks in.
    """
    command_parts = shlex.split(cfg.get("command", ""))
    # Not found: keep the name, so the SDK's spawn error names it.
    resolved = resolve_command(cfg.get("command", ""))
    command = resolved[0] if resolved else (command_parts[0] if command_parts else "")
    args = cfg.get("args", "")
    arg_list = command_parts[1:] + (shlex.split(args) if args else [])

    env = {"PATH": search_path(), **parse_env_block(cfg.get("env", ""))}
    return command, arg_list, env


class MCPManager:
    """Manages connections to one or more MCP servers."""

    def __init__(self, server_configs: list[dict[str, Any]]) -> None:
        self._configs = server_configs
        self._tools: list[dict[str, Any]] = []
        self._tool_to_session: dict[str, Any] = {}  # tool name → ClientSession
        self._tool_to_server: dict[str, str] = {}  # tool name → server name
        self._app_tools: dict[str, dict[str, str]] = {}  # tool name → {uri, server}
        self._close_event: asyncio.Event | None = None
        self._tasks: list[asyncio.Task] = []  # one long-lived task per server
        self._hook_installed = False
        self.failed_servers: list[str] = []  # names of servers that failed

    # -- lifecycle -----------------------------------------------------------

    async def connect_all(self) -> None:
        """Connect to every configured MCP server in parallel.

        One unreachable server no longer delays the others: total wait is
        the slowest single server (bounded by ``_CONNECT_TIMEOUT`` per
        step), not the sum across servers.
        """
        if not self._configs:
            return

        _install_unraisable_hook()
        self._hook_installed = True

        self._close_event = asyncio.Event()
        ready_events: list[asyncio.Event] = []
        for cfg in self._configs:
            ready = asyncio.Event()
            ready_events.append(ready)
            self._tasks.append(asyncio.create_task(self._run_server(cfg, ready)))
        # Wait for every server to finish connecting (success or failure)
        await asyncio.gather(*(e.wait() for e in ready_events))

    async def _run_server(self, cfg: dict[str, Any], ready: asyncio.Event) -> None:
        """Long-lived task owning ONE server's MCP context managers.

        anyio requires cancel scopes to be entered and exited in the same
        task, so each server's AsyncExitStack lives entirely inside its own
        task — this is what allows the servers to connect in parallel.
        """
        name = cfg.get("name") or "<unnamed>"
        problem = mcp_server_problem(cfg)
        if problem is not None:
            # A config error, said once: launching it would only fail (an empty
            # command is spawned as "" and denied).
            logger.error("MCP server %r not started: %s", name, problem)
            self.failed_servers.append(name)
            ready.set()
            return
        stack = AsyncExitStack()
        connected = False
        try:
            await stack.__aenter__()
            logger.info("Connecting to MCP server %r ...", name)
            session = await asyncio.wait_for(
                self._connect_one(cfg, stack),
                timeout=_CONNECT_TIMEOUT,
            )
            tools = await asyncio.wait_for(
                _list_all_tools(session, name),
                timeout=_CONNECT_TIMEOUT,
            )
            self._register_tools(session, tools, name)
            connected = True
            logger.info("MCP server %r: %d tools", name, len(tools))
            ready.set()

            # Keep context managers alive until close is requested
            if self._close_event is not None:
                await self._close_event.wait()
                logger.info("MCP server %r shutting down", name)

        except TimeoutError:
            logger.error("MCP server %r: timed out after %ds", name, _CONNECT_TIMEOUT)
            self.failed_servers.append(name)
        except asyncio.CancelledError:
            if not connected:
                logger.warning(
                    "MCP server %r: connection aborted (session ended before it connected)",
                    name,
                )
                self.failed_servers.append(name)
        except OSError as exc:
            # Its command is missing or not executable: the user's to fix, no traceback.
            logger.error("MCP server %r could not be started: %s", name, exc)
            self.failed_servers.append(name)
        except Exception:
            logger.exception("Failed to connect to MCP server %r", name)
            self.failed_servers.append(name)
        finally:
            ready.set()  # unblock connect_all on any exit path
            # Closed HERE, in the task that entered the stack: anyio cancel
            # scopes must exit in their own task.  Closing from another task
            # made anyio cancel this one instead, and the close then hung.
            await self._safe_close_stack(stack, name)
            logger.info("MCP server %r: stack closed", name)

    def _register_tools(self, session: Any, tools: list[Any], name: str) -> None:
        """Record a server's tools in the shared lookup tables."""
        for tool in tools:
            if tool.name in self._tool_to_session:
                logger.warning(
                    "MCP server %r tool %r ignored: name already registered by %r",
                    name,
                    tool.name,
                    self._tool_to_server.get(tool.name, "<unknown>"),
                )
                continue
            self._tool_to_session[tool.name] = session
            self._tool_to_server[tool.name] = name
            self._tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or "",
                    # mcp 2.0 renamed the SDK attribute inputSchema → input_schema
                    "parameters": _clean_schema(tool.input_schema or {}),
                }
            )
            # Track MCP App tools (tools with ui:// resourceUri)
            meta = getattr(tool, "meta", None)
            if isinstance(meta, dict):
                ui = meta.get("ui", {})
                if isinstance(ui, dict):
                    resource_uri = ui.get("resourceUri", "")
                    if isinstance(resource_uri, str) and resource_uri.startswith("ui://"):
                        self._app_tools[tool.name] = {
                            "uri": resource_uri,
                            "server": name,
                        }

    @staticmethod
    async def _safe_close_stack(stack: AsyncExitStack, name: str) -> None:
        """Exit an exit stack, swallowing any errors."""
        try:
            await stack.__aexit__(None, None, None)
        except BaseException:
            logger.debug(
                "Suppressed error closing MCP stack for %r",
                name,
            )

    async def _get_auth_provider(
        self,
        cfg: dict[str, Any],
        stack: AsyncExitStack,
    ) -> Any | None:
        """Return an ``OAuthClientProvider`` (httpx.Auth) if OAuth is configured."""
        if cfg.get("auth") != "oauth2":
            return None

        from roomkit_ui.mcp_auth import create_oauth_provider

        provider, callback_server = await create_oauth_provider(
            server_url=cfg.get("url", ""),
            server_name=cfg.get("id") or cfg.get("name", ""),
            client_id=cfg.get("oauth_client_id") or None,
            client_secret=cfg.get("oauth_client_secret") or None,
            scopes=cfg.get("oauth_scopes") or None,
        )
        stack.push_async_callback(callback_server.stop)
        return provider

    async def _connect_one(
        self,
        cfg: dict[str, Any],
        stack: AsyncExitStack,
    ) -> Any:
        """Open transport + ClientSession for a single server config."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        transport = cfg.get("transport", "stdio")

        if transport == "stdio":
            command, arg_list, env = _parse_stdio_config(cfg)

            params = StdioServerParameters(
                command=command,
                args=arg_list,
                env=env,
            )
            streams = await stack.enter_async_context(
                stdio_client(params),
            )
            read_stream, write_stream = streams

        elif transport == "sse":
            from mcp.client.sse import sse_client

            url = validate_mcp_http_url(cfg.get("url", ""))
            auth = await self._get_auth_provider(cfg, stack)
            streams = await stack.enter_async_context(sse_client(url, auth=auth))
            read_stream, write_stream = streams

        elif transport == "streamable_http":
            from mcp.client.streamable_http import streamable_http_client

            url = validate_mcp_http_url(cfg.get("url", ""))
            auth = await self._get_auth_provider(cfg, stack)
            http_client = None
            if auth is not None:
                from mcp.shared._httpx_utils import create_mcp_http_client

                http_client = create_mcp_http_client(auth=auth)
                stack.push_async_callback(http_client.aclose)
            streams = await stack.enter_async_context(
                streamable_http_client(url, http_client=http_client),
            )
            read_stream, write_stream = streams[0], streams[1]

        else:
            raise ValueError(f"Unknown MCP transport: {transport!r}")

        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream),
        )
        await session.initialize()
        return session

    async def close_all(self) -> None:
        """Signal the server tasks to exit and wait for cleanup."""
        logger.info("close_all: signalling shutdown")
        if self._close_event:
            self._close_event.set()
        else:
            # _close_event is None → connect_all raised before setting it.
            # Cancel the tasks directly to avoid a 15s hang.
            for task in self._tasks:
                task.cancel()
        if self._tasks:
            logger.info(
                "close_all: waiting for %d server task(s) (timeout=15s) …", len(self._tasks)
            )
            try:
                # Use asyncio.wait (not wait_for) to avoid auto-cancelling
                # the tasks on timeout — they need uninterrupted time to
                # properly terminate MCP subprocesses.
                done, pending = await asyncio.wait(self._tasks, timeout=15)
                if not pending:
                    logger.info("close_all: all server tasks finished normally")
                else:
                    logger.warning("close_all: %d task(s) timed out, cancelling", len(pending))
                    for task in pending:
                        task.cancel()
                    for task in pending:
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
            except Exception:
                logger.exception("Error during MCP shutdown")
        self._tasks = []
        self._tools.clear()
        self._tool_to_session.clear()
        self._tool_to_server.clear()
        self._app_tools.clear()
        if self._hook_installed:
            _uninstall_unraisable_hook()
            self._hook_installed = False
        logger.info("close_all: done")

    # -- tools ---------------------------------------------------------------

    def get_tools(self) -> list[dict[str, Any]]:
        """Return discovered tools in roomkit format."""
        return list(self._tools)

    def get_app_tool_info(self, tool_name: str) -> dict[str, str] | None:
        """Return ``{uri, server}`` if *tool_name* is an MCP App tool."""
        return self._app_tools.get(tool_name)

    def get_tool_server(self, tool_name: str) -> str | None:
        """Return the configured server that owns *tool_name*, if discovered."""
        return self._tool_to_server.get(tool_name)

    async def read_resource(self, tool_name: str, uri: str) -> str | None:
        """Fetch an MCP resource (e.g. ``ui://`` HTML) from the owning server."""
        session = self._tool_to_session.get(tool_name)
        if session is None:
            logger.warning("read_resource: no session for tool %r", tool_name)
            return None
        try:
            # mcp 2.x takes the URI as a str; an AnyUrl fails its validation.
            result = await asyncio.wait_for(
                session.read_resource(uri),
                timeout=_CONNECT_TIMEOUT,
            )
            for content in result.contents:
                if hasattr(content, "text"):
                    return str(content.text)
        except Exception:
            logger.exception("read_resource(%r, %r) failed", tool_name, uri)
        return None

    async def handle_tool_call(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Route a tool call to the owning MCP server and return the result.

        Matches the 0.7.x unified ``ToolHandler`` signature: ``async
        (name, arguments) -> str``. A call that ran and failed raises
        ``ToolFailedError``: Gemini reads any returned body as a success, and
        only a raised failure reaches it under its ``error`` key.
        """
        from mcp.shared.exceptions import MCPError
        from roomkit import ToolFailedError

        mcp_session = self._tool_to_session.get(name)
        if mcp_session is None:
            # roomkit reads this envelope as "not served here", not a result.
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            result = await asyncio.wait_for(
                mcp_session.call_tool(name, arguments),
                timeout=_TOOL_CALL_TIMEOUT,
            )
        except TimeoutError:
            logger.error("MCP tool call %r timed out after %ds", name, _TOOL_CALL_TIMEOUT)
            raise ToolFailedError(f"Tool call timed out after {_TOOL_CALL_TIMEOUT}s") from None
        except MCPError as exc:
            # The server's own words, as an is_error result would carry them.
            logger.warning("MCP tool call %r failed: %s", name, exc)
            raise ToolFailedError(exc.message) from exc
        except Exception as exc:
            # The message can hold anything (a URL, a path): the log keeps it,
            # the model reads the class only — roomkit's rule for a failure.
            logger.exception("MCP tool call %r failed", name)
            raise ToolFailedError(f"The MCP server call failed ({type(exc).__name__})") from exc
        output = "\n".join(c.text for c in result.content if hasattr(c, "text"))
        if result.is_error:  # mcp 2.0 renamed isError → is_error
            raise ToolFailedError(output or f"Tool {name!r} reported an error")
        return json.dumps({"result": output})

    async def handle_app_tool_call(
        self,
        origin_server: str,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Route an MCP App ``tools/call`` only to tools from the same server."""
        owner = self.get_tool_server(name)
        if owner is None:
            logger.warning(
                "Blocked MCP App tool call from %r to unknown tool %r",
                origin_server,
                name,
            )
            return json.dumps({"error": "Tool is not available to this MCP App"})
        if owner != origin_server:
            logger.warning(
                "Blocked MCP App tool call from %r to tool %r owned by %r",
                origin_server,
                name,
                owner,
            )
            return json.dumps({"error": "Tool is not available to this MCP App"})
        from roomkit import ToolFailedError

        try:
            return await self.handle_tool_call(name, arguments)
        except ToolFailedError as failure:
            # The app reads the envelope (mcp_app_bridge), not an exception.
            return json.dumps({"error": failure.message})
