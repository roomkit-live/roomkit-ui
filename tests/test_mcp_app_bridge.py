import ipaddress

import pytest

import roomkit_ui.url_policy as url_policy
from roomkit_ui.mcp_app_bridge import MCPAppBridge


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    table = {"example.com": "93.184.215.14", "127.0.0.1.nip.io": "127.0.0.1"}

    def resolve(name):
        if name not in table:
            raise OSError(name)
        return [ipaddress.ip_address(table[name])]

    monkeypatch.setattr(url_policy, "_resolve", resolve)
    url_policy.clear_resolve_cache()
    yield
    url_policy.clear_resolve_cache()


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
    # Forms a browser dials as loopback, which urlparse took for public names.
    MCPAppBridge._handle_open_link({"url": "http://2130706433/admin"})
    MCPAppBridge._handle_open_link({"url": "http://127.1/admin"})
    MCPAppBridge._handle_open_link({"url": "http://127.0.0.1.nip.io/admin"})

    assert opened == []


def test_open_link_opens_the_checked_url_not_the_one_sent(monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    MCPAppBridge._handle_open_link({"url": "http://127.0.0.1\\@example.com/"})

    assert opened == ["http://example.com/"]
