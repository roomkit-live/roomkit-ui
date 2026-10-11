"""The MCP page's OAuth flow may outlive the Settings dialog that started it."""

from __future__ import annotations

import asyncio

import shiboken6

import roomkit_ui.mcp_auth as mcp_auth
from roomkit_ui.widgets.settings.mcp_page import _MCPPage


async def test_an_oauth_flow_ending_after_settings_closed_leaves_the_page_alone(
    qapp, monkeypatch, caplog
):
    # The browser wait lasts up to 320 s; closing Settings meanwhile
    # destroys the page while the flow is still awaiting.
    gate = asyncio.Event()

    async def slow_provider(**_kwargs):
        await gate.wait()
        raise TimeoutError

    monkeypatch.setattr(mcp_auth, "create_oauth_provider", slow_provider)
    page = _MCPPage({})
    task = asyncio.ensure_future(page._run_oauth_flow("srv", "https://mcp.example/"))
    await asyncio.sleep(0)

    shiboken6.delete(page)
    gate.set()
    await task  # raised RuntimeError on the deleted status label before

    assert task.exception() is None
