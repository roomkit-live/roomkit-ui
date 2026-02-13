"""OAuth2 authentication support for MCP HTTP servers.

Implements token storage (QSettings-backed), a local callback server for the
Authorization Code + PKCE flow, and a factory that wires everything together
into an ``OAuthClientProvider`` (``httpx.Auth`` subclass) that the MCP SDK
transports accept directly.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

_SETTINGS_PREFIX = "room/mcp_oauth"


# ---------------------------------------------------------------------------
# Token storage (QSettings-backed)
# ---------------------------------------------------------------------------


class QSettingsTokenStorage:
    """Implements ``mcp.client.auth.TokenStorage`` backed by QSettings.

    Each server gets its own key namespace under ``room/mcp_oauth/{name}/``.
    """

    def __init__(self, server_name: str) -> None:
        self._name = server_name
        self._qs = QSettings()

    def _key(self, suffix: str) -> str:
        return f"{_SETTINGS_PREFIX}/{self._name}/{suffix}"

    # -- TokenStorage protocol -----------------------------------------------

    async def get_tokens(self):  # noqa: ANN201
        from mcp.shared.auth import OAuthToken

        raw = self._qs.value(self._key("tokens"), None)
        if raw is None:
            return None
        try:
            return OAuthToken.model_validate_json(raw)
        except Exception:
            logger.debug("Failed to deserialize stored tokens for %r", self._name)
            return None

    async def set_tokens(self, tokens) -> None:
        self._qs.setValue(self._key("tokens"), tokens.model_dump_json())
        self._qs.sync()

    async def get_client_info(self):  # noqa: ANN201
        from mcp.shared.auth import OAuthClientInformationFull

        raw = self._qs.value(self._key("client_info"), None)
        if raw is None:
            return None
        try:
            return OAuthClientInformationFull.model_validate_json(raw)
        except Exception:
            logger.debug("Failed to deserialize stored client_info for %r", self._name)
            return None

    async def set_client_info(self, client_info) -> None:
        self._qs.setValue(self._key("client_info"), client_info.model_dump_json())
        self._qs.sync()


# ---------------------------------------------------------------------------
# Local OAuth callback server
# ---------------------------------------------------------------------------


class LocalOAuthCallbackServer:
    """Tiny HTTP server on ``127.0.0.1`` that receives the OAuth redirect.

    Parses ``?code=...&state=...`` (or ``?error=...``) from the browser
    redirect, sends back a friendly HTML page, and resolves a future.
    """

    def __init__(self) -> None:
        self._port: int = 0
        self._server: asyncio.Server | None = None
        self._future: asyncio.Future[tuple[str, str | None]] | None = None

    async def start(self) -> None:
        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self._port = s.getsockname()[1]
        self._future = asyncio.get_running_loop().create_future()
        self._server = await asyncio.start_server(self._handle_connection, "127.0.0.1", self._port)
        logger.info("OAuth callback server listening on port %d", self._port)

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self._port}/callback"

    async def wait_for_callback(self, timeout: float = 300) -> tuple[str, str | None]:
        """Wait for the browser redirect. Returns ``(code, state)``."""
        assert self._future is not None  # noqa: S101
        return await asyncio.wait_for(self._future, timeout=timeout)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            request_line = data.split(b"\r\n")[0].decode("utf-8", errors="replace")
            # e.g. "GET /callback?code=abc&state=xyz HTTP/1.1"
            parts = request_line.split(" ")
            path = parts[1] if len(parts) > 1 else ""
            parsed = urlparse(path)
            params = parse_qs(parsed.query)

            error = params.get("error", [None])[0]
            if error:
                desc = params.get("error_description", [error])[0]
                body = (
                    "<html><body style='font-family:sans-serif;text-align:center;"
                    "padding:60px'>"
                    f"<h2>Authorization Failed</h2><p>{desc}</p>"
                    "<p>You can close this tab.</p></body></html>"
                )
                self._send_response(writer, 200, body)
                if self._future and not self._future.done():
                    self._future.set_exception(RuntimeError(f"OAuth error: {desc}"))
                return

            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]

            if code:
                body = (
                    "<html><body style='font-family:sans-serif;text-align:center;"
                    "padding:60px'>"
                    "<h2>Authorization Complete</h2>"
                    "<p>You can close this tab and return to RoomKit.</p>"
                    "</body></html>"
                )
                self._send_response(writer, 200, body)
                if self._future and not self._future.done():
                    self._future.set_result((code, state))
            else:
                body = (
                    "<html><body style='font-family:sans-serif;text-align:center;"
                    "padding:60px'>"
                    "<h2>Missing authorization code</h2>"
                    "<p>You can close this tab.</p></body></html>"
                )
                self._send_response(writer, 400, body)
        except Exception:
            logger.debug("OAuth callback handler error", exc_info=True)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    def _send_response(writer: asyncio.StreamWriter, status: int, body: str) -> None:
        reason = "OK" if status == 200 else "Bad Request"
        encoded = body.encode("utf-8")
        header = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(encoded)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        writer.write(header.encode("utf-8") + encoded)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("OAuth callback server stopped")


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


async def create_oauth_provider(
    server_url: str,
    server_name: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    scopes: str | None = None,
) -> tuple:
    """Create an ``OAuthClientProvider`` + callback server for *server_url*.

    Returns ``(provider, callback_server)`` — the caller must manage the
    callback server's lifecycle (call ``stop()`` when done).
    """
    import webbrowser

    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata

    callback_server = LocalOAuthCallbackServer()
    await callback_server.start()

    storage = QSettingsTokenStorage(server_name)

    redirect_uri = callback_server.redirect_uri
    auth_method = "none" if not client_secret else "client_secret_post"

    metadata = OAuthClientMetadata(
        redirect_uris=[redirect_uri],
        token_endpoint_auth_method=auth_method,
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=scopes or None,
        client_name="RoomKit UI",
    )

    # Pre-populate client registration if client_id is provided
    if client_id:
        client_info = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret or None,
            redirect_uris=[redirect_uri],
            token_endpoint_auth_method=auth_method,
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=scopes or None,
            client_name="RoomKit UI",
        )
        await storage.set_client_info(client_info)

    async def redirect_handler(auth_url: str) -> None:
        logger.info("Opening browser for OAuth: %s", auth_url)
        webbrowser.open(auth_url)

    async def callback_handler() -> tuple[str, str | None]:
        return await callback_server.wait_for_callback()

    provider = OAuthClientProvider(
        server_url=server_url,
        client_metadata=metadata,
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    return provider, callback_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def clear_oauth_tokens(server_name: str) -> None:
    """Remove stored OAuth tokens for *server_name*."""
    qs = QSettings()
    qs.remove(f"{_SETTINGS_PREFIX}/{server_name}")
    qs.sync()


def has_oauth_tokens(server_name: str) -> bool:
    """Return ``True`` if tokens are stored for *server_name*."""
    qs = QSettings()
    return qs.value(f"{_SETTINGS_PREFIX}/{server_name}/tokens", None) is not None
