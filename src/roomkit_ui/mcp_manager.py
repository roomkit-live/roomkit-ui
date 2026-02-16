"""MCP (Model Context Protocol) client manager.

Connects to configured MCP servers, collects their tools, and routes
tool calls from the voice assistant to the correct server.

All MCP context managers live inside a single long-running asyncio Task
so that anyio cancel-scopes are entered and exited in the same task
(required by anyio, which MCP uses internally).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

_CONNECT_TIMEOUT = 30  # seconds per server
_TOOL_CALL_TIMEOUT = 60  # seconds per tool call

# JSON Schema keys that voice providers (especially Gemini) reject.
_STRIP_SCHEMA_KEYS = {"$schema", "additionalProperties"}

logger = logging.getLogger(__name__)


def _unraisable_hook(unraisable: sys.UnraisableHookArgs) -> None:
    """Suppress noisy RuntimeError from anyio cancel-scope during MCP cleanup.

    When an MCP task is cancelled, the streamable_http_client async generator
    may be finalized by GC in a different task context, triggering an anyio
    "Attempted to exit cancel scope in a different task" RuntimeError.
    This is harmless — log it at debug level instead of printing a traceback.
    """
    exc = unraisable.exc_value
    if isinstance(exc, RuntimeError) and "cancel scope" in str(exc):
        logger.debug("Suppressed anyio cancel-scope error during cleanup: %s", exc)
        return
    sys.__unraisablehook__(unraisable)


sys.unraisablehook = _unraisable_hook


def _clean_schema(obj: Any) -> Any:
    """Recursively strip JSON Schema keys that voice providers reject."""
    if isinstance(obj, dict):
        return {k: _clean_schema(v) for k, v in obj.items() if k not in _STRIP_SCHEMA_KEYS}
    if isinstance(obj, list):
        return [_clean_schema(v) for v in obj]
    return obj


class MCPManager:
    """Manages connections to one or more MCP servers."""

    def __init__(self, server_configs: list[dict[str, Any]]) -> None:
        self._configs = server_configs
        self._tools: list[dict[str, Any]] = []
        self._tool_to_session: dict[str, Any] = {}  # tool name → ClientSession
        self._app_tools: dict[str, dict[str, str]] = {}  # tool name → {uri, server}
        self._close_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self.failed_servers: list[str] = []  # names of servers that failed

    # -- lifecycle -----------------------------------------------------------

    async def connect_all(self) -> None:
        """Connect to every configured MCP server and discover tools."""
        if not self._configs:
            return

        self._close_event = asyncio.Event()
        ready = asyncio.Event()

        self._task = asyncio.create_task(self._run(ready))
        # Wait for all servers to finish connecting (or timeout)
        await ready.wait()

    async def _run(self, ready: asyncio.Event) -> None:
        """Long-lived task owning all MCP context managers.

        Each server gets its own AsyncExitStack so that a failed connection
        can be cleaned up independently without crashing the whole task.
        """
        server_stacks: list[AsyncExitStack] = []
        connecting_name: str | None = None  # server currently being connected
        try:
            for cfg in self._configs:
                name = cfg.get("name", "<unnamed>")
                connecting_name = name
                stack = AsyncExitStack()
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
                    for tool in result.tools:
                        self._tool_to_session[tool.name] = session
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
                                if isinstance(resource_uri, str) and resource_uri.startswith(
                                    "ui://"
                                ):
                                    self._app_tools[tool.name] = {
                                        "uri": resource_uri,
                                        "server": name,
                                    }
                    server_stacks.append(stack)
                    connecting_name = None
                    logger.info(
                        "MCP server %r: %d tools",
                        name,
                        len(result.tools),
                    )
                except TimeoutError:
                    logger.error(
                        "MCP server %r: timed out after %ds",
                        name,
                        _CONNECT_TIMEOUT,
                    )
                    self.failed_servers.append(name)
                    await self._safe_close_stack(stack, name)
                except Exception:
                    logger.exception(
                        "Failed to connect to MCP server %r",
                        name,
                    )
                    self.failed_servers.append(name)
                    await self._safe_close_stack(stack, name)

            # Signal caller that tools are ready
            ready.set()

            # Keep context managers alive until close is requested
            if server_stacks and self._close_event is not None:
                await self._close_event.wait()
                logger.info("MCP manager shutting down")
            else:
                logger.info("No MCP servers connected")

        except asyncio.CancelledError:
            if connecting_name:
                logger.warning(
                    "MCP server %r: connection aborted (session ended before it connected)",
                    connecting_name,
                )
                self.failed_servers.append(connecting_name)
            else:
                logger.info("MCP manager shutting down")
        except Exception:
            logger.exception("MCP manager task failed")
        finally:
            ready.set()  # unblock caller if we failed early
            # Clean up all successfully-connected servers.
            # Shield from cancellation so the subprocess gets properly
            # terminated even if close_all() is impatient.
            for i, stack in enumerate(server_stacks):
                logger.info("_run finally: closing stack %d/%d …", i + 1, len(server_stacks))
                try:
                    await asyncio.shield(self._safe_close_stack(stack, "<cleanup>"))
                except asyncio.CancelledError:
                    # shield was cancelled but the inner coro may still
                    # be running — give it one more chance
                    logger.info("_run finally: shield cancelled for stack %d, retrying", i + 1)
                    try:
                        await asyncio.wait_for(
                            self._safe_close_stack(stack, "<cleanup>"), timeout=5.0
                        )
                    except TimeoutError:
                        logger.error("_run finally: retry timed out for stack %d", i + 1)
                logger.info("_run finally: stack %d closed", i + 1)
            logger.info("_run finally: all stacks closed")

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
            command_parts = cfg.get("command", "").split()
            command = command_parts[0] if command_parts else ""
            args = cfg.get("args", "")
            arg_list = command_parts[1:] + (args.split() if args else [])

            env: dict[str, str] | None = None
            env_str = cfg.get("env", "")
            if env_str and env_str.strip():
                env = os.environ.copy()
                for line in env_str.strip().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()

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
        """Signal the background task to exit and wait for cleanup."""
        logger.info("close_all: signalling shutdown")
        if self._close_event:
            self._close_event.set()
        if self._task:
            logger.info("close_all: waiting for _run task (timeout=15s) …")
            try:
                # Use asyncio.wait (not wait_for) to avoid auto-cancelling
                # the task on timeout — the task needs uninterrupted time
                # to properly terminate MCP subprocesses.
                done, _ = await asyncio.wait([self._task], timeout=15)
                if done:
                    logger.info("close_all: _run task finished normally")
                else:
                    logger.warning("close_all: timed out after 15s, cancelling task")
                    self._task.cancel()
                    try:
                        await self._task
                    except asyncio.CancelledError:
                        logger.info("close_all: task cancelled")
            except Exception:
                logger.exception("Error during MCP shutdown")
            self._task = None
        self._tools.clear()
        self._tool_to_session.clear()
        self._app_tools.clear()
        logger.info("close_all: done")

    # -- tools ---------------------------------------------------------------

    def get_tools(self) -> list[dict[str, Any]]:
        """Return discovered tools in roomkit format."""
        return list(self._tools)

    def get_app_tool_info(self, tool_name: str) -> dict[str, str] | None:
        """Return ``{uri, server}`` if *tool_name* is an MCP App tool."""
        return self._app_tools.get(tool_name)

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
        _session: Any,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Route a tool call to the owning MCP server and return the result."""
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
