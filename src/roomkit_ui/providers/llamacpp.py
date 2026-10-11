"""llama.cpp AI provider factory: a local GGUF model roomkit runs itself.

roomkit's ``LlamaCppAIProvider`` downloads a pinned ``llama-server`` build
and the model, starts the server on first use and stops it on ``close()``.
A session closes its AI provider when it ends, so used as is, every session
would pay the model load again.  Here the server outlives the session: one
per configuration, kept until the configuration changes or the app quits
(roomkit kills a server still running at interpreter exit).

The server runs on a thread and event loop of its own.  When a session ends
the engine strips the app's loop of every file descriptor the session
registered (``cleanup.cleanup_stale_fds``, the anyio leak fix): a server
started during a session and read from that loop would lose its log pipe,
and block once the pipe filled.  What each session gets is only an HTTP
client on the app's loop, closed with the session.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
from typing import Any

logger = logging.getLogger(__name__)

# roomkit's own documented default (LlamaCppConfig, examples/llamacpp_tools.py).
DEFAULT_MODEL = "unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"

_shared: tuple[tuple, _ServerThread] | None = None


def create(settings: dict) -> Any:
    """Create this session's llama.cpp provider, a client of the shared server."""
    from roomkit.providers.llamacpp import LlamaCppAIProvider, LlamaCppConfig

    model = (settings.get("vc_llamacpp_model", "") or "").strip() or DEFAULT_MODEL
    server = _shared_server(model, _context_size(settings))

    class _SessionLlamaCpp(LlamaCppAIProvider):
        """Starts the shared server rather than its own; close() leaves it running."""

        async def start(self) -> None:
            await server.start()

        async def close(self) -> None:
            # Only the HTTP client: LlamaCppAIProvider.close() stops the server.
            await super(LlamaCppAIProvider, self).close()

    return _SessionLlamaCpp(
        LlamaCppConfig(
            model=model,
            context_size=server.context_size,
            port=server.port,
            # A spoken reply cannot wait for a reasoning trace (roomkit's
            # voice_local_pocket_fr example makes the same call).
            enable_thinking=False,
        )
    )


def _context_size(settings: dict) -> int | None:
    """The context window the user set, or None for roomkit's default."""
    raw = str(settings.get("vc_llamacpp_context", "") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _shared_server(model: str, context_size: int | None) -> _ServerThread:
    """The server for this configuration; one built for another is stopped."""
    global _shared
    key = (model, context_size)
    if _shared is not None and _shared[0] == key:
        return _shared[1]
    if _shared is not None:
        _shared[1].shutdown()
    server = _ServerThread(model, context_size)
    _shared = (key, server)
    return server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _ServerThread:
    """One ``llama-server``, driven from its own thread's event loop."""

    def __init__(self, model: str, context_size: int | None) -> None:
        from roomkit.providers.llamacpp import LlamaCppConfig
        from roomkit.providers.llamacpp.server import LlamaServer

        self.port = _free_port()
        config = LlamaCppConfig(model=model, port=self.port)
        if context_size is not None:
            config = config.model_copy(update={"context_size": context_size})
        self.context_size: int = config.context_size
        self._server = LlamaServer(config)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="llama-server", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def start(self) -> None:
        """Download what is missing and start the server; return once it serves.

        Idempotent, and starts again a server that died.  Cancelling the
        caller cancels the start, which stops a half-started server.
        """
        future = asyncio.run_coroutine_threadsafe(self._server.start(), self._loop)
        await asyncio.wrap_future(future)

    def shutdown(self) -> None:
        """Stop the server, then the thread, without waiting for either."""
        future = asyncio.run_coroutine_threadsafe(self._server.stop(), self._loop)
        future.add_done_callback(lambda _: self._loop.call_soon_threadsafe(self._loop.stop))
        logger.info("llama-server on port %d: stopping, the configuration changed", self.port)
