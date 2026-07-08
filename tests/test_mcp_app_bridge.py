from roomkit_ui.mcp_app_bridge import MCPAppBridge


def test_open_link_allows_public_http_url(monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    MCPAppBridge._handle_open_link({"url": "https://example.com/path?token=secret"})

    assert opened == ["https://example.com/path?token=secret"]


def test_open_link_blocks_private_or_non_http_urls(monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    MCPAppBridge._handle_open_link({"url": "http://127.0.0.1:8000/admin"})
    MCPAppBridge._handle_open_link({"url": "file:///etc/passwd"})

    assert opened == []
