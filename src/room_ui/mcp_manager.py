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
from contextlib import AsyncExitStack
from typing import Any

_CONNECT_TIMEOUT = 30  # seconds per server

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages connections to one or more MCP servers."""

    def __init__(self, server_configs: list[dict[str, Any]]) -> None:
        self._configs = server_configs
        self._tools: list[dict[str, Any]] = []
        self._tool_to_session: dict[str, Any] = {}  # tool name → ClientSession
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
        try:
            for cfg in self._configs:
                name = cfg.get("name", "<unnamed>")
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
                                "parameters": tool.inputSchema,
                            }
                        )
                    server_stacks.append(stack)
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
                except BaseException:
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
            logger.info("MCP manager task cancelled")
        except BaseException:
            logger.exception("MCP manager task failed")
        finally:
            ready.set()  # unblock caller if we failed early
            # Clean up all successfully-connected servers
            for stack in server_stacks:
                await self._safe_close_stack(stack, "<cleanup>")

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
            command = cfg.get("command", "")
            args = cfg.get("args", "")
            arg_list = args.split() if args else []

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
            streams = await stack.enter_async_context(sse_client(url))
            read_stream, write_stream = streams

        elif transport == "streamable_http":
            from mcp.client.streamable_http import streamablehttp_client

            url = cfg.get("url", "")
            streams = await stack.enter_async_context(
                streamablehttp_client(url),
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
        if self._close_event:
            self._close_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except TimeoutError:
                logger.warning("MCP shutdown timed out, cancelling task")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            except BaseException:
                logger.exception("Error during MCP shutdown")
            self._task = None
        self._tools.clear()
        self._tool_to_session.clear()

    # -- tools ---------------------------------------------------------------

    def get_tools(self) -> list[dict[str, Any]]:
        """Return discovered tools in roomkit format."""
        return list(self._tools)

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
            result = await mcp_session.call_tool(name, arguments)
            texts: list[str] = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
            output = "\n".join(texts) if texts else ""
            if result.isError:
                return json.dumps({"error": output})
            return json.dumps({"result": output})
        except Exception as exc:
            logger.exception("MCP tool call %r failed", name)
            return json.dumps({"error": str(exc)})
