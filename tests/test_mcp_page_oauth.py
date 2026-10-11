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


async def test_authorization_keeps_its_credentials_and_does_not_report_on_another_server(
    qapp, monkeypatch
):
    gate = asyncio.Event()
    captured = []

    async def provider(**kwargs):
        captured.append(kwargs)
        await gate.wait()
        raise TimeoutError

    monkeypatch.setattr(mcp_auth, "create_oauth_provider", provider)
    monkeypatch.setattr(mcp_auth, "has_oauth_tokens", lambda *args: False)
    page = _MCPPage({})
    try:
        page._add_server()
        page._name_edit.setText("First")
        page._transport_combo.setCurrentIndex(2)
        page._auth_combo.setCurrentIndex(1)
        page._url_edit.setText("https://first.example/mcp")
        page._oauth_client_id.setText("first-client")
        page._oauth_client_secret.setText("first-secret")
        server_id = page._current_server_id()
        before = asyncio.all_tasks()
        page._on_authorize_clicked()
        tasks = asyncio.all_tasks() - before
        assert not page._authorize_btn.isEnabled()
        # Change the editor before the async function gets its first turn.
        page._add_server()
        page._name_edit.setText("Second")
        page._transport_combo.setCurrentIndex(2)
        page._auth_combo.setCurrentIndex(1)
        page._url_edit.setText("https://second.example/mcp")
        page._oauth_client_id.setText("second-client")
        page._oauth_client_secret.setText("second-secret")
        await asyncio.sleep(0)
        assert captured == [
            {
                "server_url": "https://first.example/mcp",
                "server_name": server_id,
                "client_id": "first-client",
                "client_secret": "first-secret",
                "scopes": None,
            }
        ]
        gate.set()
        await asyncio.gather(*tasks)
        assert page._oauth_status.text() == "Not authorized"
        assert page._authorize_btn.isEnabled()
        page._show_edit(0)
        assert page._oauth_status.text() == "Authorization timed out"
        page._url_edit.setText("https://different.example/mcp")
        assert page._oauth_status.text() == "Not authorized"
    finally:
        shiboken6.delete(page)


async def test_a_probe_without_a_token_is_not_reported_as_authorized(qapp, monkeypatch):
    import httpx

    stopped = []

    class Callback:
        async def stop(self):
            stopped.append(True)

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return httpx.Response(200)

    async def provider(**kwargs):
        return None, Callback()

    monkeypatch.setattr(mcp_auth, "create_oauth_provider", provider)
    monkeypatch.setattr(mcp_auth, "has_oauth_tokens", lambda *args: False)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    page = _MCPPage({})
    try:
        page._add_server()
        page._name_edit.setText("Public endpoint")
        page._url_edit.setText("https://public.example/mcp")
        await page._run_oauth_flow(page._current_server_id(), page._url_edit.text())
        assert page._oauth_status.text() == "No OAuth token received"
        assert page._authorize_btn.isEnabled()
        assert stopped == [True]
    finally:
        shiboken6.delete(page)
