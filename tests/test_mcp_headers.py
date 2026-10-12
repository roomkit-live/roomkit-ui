"""HTTP headers for an MCP server (``Authorization: Bearer …``): read from the
settings page's block, kept in the keychain, sent on every request."""

import asyncio
import json
import socket

import pytest

from roomkit_ui.mcp_config import invalid_header_lines, parse_mcp_headers
from roomkit_ui.mcp_manager import MCPManager

TOKEN = "Bearer s3cret"


def test_header_lines_read_as_typed_or_pasted_from_a_json_config():
    raw = 'Authorization: Bearer abc\n"X-Api-Key": "k1",\n\nnot a header\nEmpty:'

    assert parse_mcp_headers(raw) == {"Authorization": "Bearer abc", "X-Api-Key": "k1"}
    assert invalid_header_lines(raw) == 2  # counted, never shown: a line may be a credential


@pytest.fixture
async def guarded_server():
    """A streamable-HTTP MCP server that answers only a request bearing TOKEN."""
    import uvicorn
    from mcp.server.mcpserver import MCPServer

    mcp_server = MCPServer("guarded")

    @mcp_server.tool()
    def ping() -> str:
        return "pong"

    inner = mcp_server.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http" and dict(scope["headers"]).get(b"authorization") != (
            TOKEN.encode()
        ):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await inner(scope, receive, send)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.01)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
    server.should_exit = True
    await asyncio.wait_for(task, 5)


@pytest.mark.parametrize(("headers", "tools"), [(f"Authorization: {TOKEN}", ["ping"]), ("", [])])
async def test_a_streamable_http_server_gets_the_headers(guarded_server, headers, tools):
    manager = MCPManager(
        [
            {
                "name": "guarded",
                "transport": "streamable_http",
                "url": guarded_server,
                "headers": headers,
            }
        ]
    )
    try:
        await manager.connect_all()
        assert [tool["name"] for tool in manager.get_tools()] == tools
    finally:
        await asyncio.wait_for(manager.close_all(), timeout=5)


def test_the_settings_page_edits_the_headers_of_an_http_server(qapp):
    import shiboken6

    from roomkit_ui.widgets.settings.mcp_page import MCP_TRANSPORTS, _MCPPage

    page = _MCPPage({})
    try:
        page._add_server()
        assert page._headers_edit.isHidden()  # stdio: no request to put a header on
        page._name_edit.setText("home")
        http = [value for _, value in MCP_TRANSPORTS].index("streamable_http")
        page._transport_combo.setCurrentIndex(http)
        page._url_edit.setText("http://192.168.50.253/mcp")
        assert not page._headers_edit.isHidden()

        page._headers_edit.setPlainText(f"Authorization: {TOKEN}")

        [saved] = json.loads(page.get_servers_json())
        assert saved["headers"] == f"Authorization: {TOKEN}"
        assert "unencrypted" in page._connection_status.text()
        page._headers_edit.setPlainText(f"Authorization {TOKEN}")
        assert "1 header line(s)" in page._connection_status.text()
        assert TOKEN not in page._connection_status.text()
    finally:
        shiboken6.delete(page)
