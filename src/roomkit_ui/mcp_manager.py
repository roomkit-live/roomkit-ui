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
import os
import shlex
import sys
from contextlib import AsyncExitStack
from typing import Any

_CONNECT_TIMEOUT = 10  # seconds per connection step, per server
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


def _parse_stdio_config(cfg: dict[str, Any]) -> tuple[str, list[str], dict[str, str] | None]:
    """Parse a stdio server config into (command, args, env).

    shlex honours quoting, so executables with spaces in their path
    (e.g. ``"/Applications/My App/server"``) parse as one token.
    """
    command_parts = shlex.split(cfg.get("command", ""))
    command = command_parts[0] if command_parts else ""
    args = cfg.get("args", "")
    arg_list = command_parts[1:] + (shlex.split(args) if args else [])

    env: dict[str, str] | None = None
    env_str = cfg.get("env", "")
    if env_str and env_str.strip():
        env = os.environ.copy()
        for line in env_str.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
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
        name = cfg.get("name", "<unnamed>")
        stack = AsyncExitStack()
        connected = False
        try:
            await stack.__aenter__()
            logger.info("Connecting to MCP server %r ...", name)
            session = await asyncio.wait_for(
                self._connect_one(cfg, stack),
                timeout=_CONNECT_TIMEOUT,
            )
            result = await asyncio.wait_for(
                session.list_tools(),
                timeout=_CONNECT_TIMEOUT,
            )
            self._register_tools(session, result, name)
            connected = True
            logger.info("MCP server %r: %d tools", name, len(result.tools))
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
        except Exception:
            logger.exception("Failed to connect to MCP server %r", name)
            self.failed_servers.append(name)
        finally:
            ready.set()  # unblock connect_all on any exit path
            # Shield the close from cancellation so the subprocess gets
            # properly terminated even if close_all() is impatient.
            close_task = asyncio.ensure_future(self._safe_close_stack(stack, name))
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError:
                # Shield was cancelled but close_task continues.
                # Wait for the *same* task to finish — no double-close.
                logger.info("MCP server %r: close shield cancelled, retrying", name)
                try:
                    await asyncio.wait_for(close_task, timeout=5.0)
                except (TimeoutError, asyncio.CancelledError):
                    logger.error("MCP server %r: stack close retry failed", name)
            logger.info("MCP server %r: stack closed", name)

    def _register_tools(self, session: Any, result: Any, name: str) -> None:
        """Record a server's tools in the shared lookup tables."""
        for tool in result.tools:
            self._tool_to_session[tool.name] = session
            self._tool_to_server[tool.name] = name
            self._tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": _clean_schema(tool.inputSchema or {}),
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
            server_name=cfg.get("name", ""),
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

            url = cfg.get("url", "")
            auth = await self._get_auth_provider(cfg, stack)
            streams = await stack.enter_async_context(sse_client(url, auth=auth))
            read_stream, write_stream = streams

        elif transport == "streamable_http":
            from mcp.client.streamable_http import streamable_http_client

            url = cfg.get("url", "")
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
            from pydantic import AnyUrl

            result = await asyncio.wait_for(
                session.read_resource(AnyUrl(uri)),
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
        (name, arguments) -> str``.
        """
        mcp_session = self._tool_to_session.get(name)
        if mcp_session is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            result = await asyncio.wait_for(
                mcp_session.call_tool(name, arguments),
                timeout=_TOOL_CALL_TIMEOUT,
            )
            texts: list[str] = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
            output = "\n".join(texts) if texts else ""
            if result.isError:
                return json.dumps({"error": output})
            return json.dumps({"result": output})
        except TimeoutError:
            logger.error("MCP tool call %r timed out after %ds", name, _TOOL_CALL_TIMEOUT)
            return json.dumps({"error": f"Tool call timed out after {_TOOL_CALL_TIMEOUT}s"})
        except Exception as exc:
            logger.exception("MCP tool call %r failed", name)
            return json.dumps({"error": str(exc)})

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
        return await self.handle_tool_call(name, arguments)
