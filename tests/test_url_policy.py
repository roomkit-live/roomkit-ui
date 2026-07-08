from roomkit_ui.url_policy import (
    is_local_or_private_host,
    is_public_http_url,
    is_public_web_url,
    safe_url_for_log,
)


def test_local_or_private_hosts_are_blocked():
    assert is_local_or_private_host("localhost")
    assert is_local_or_private_host("app.localhost")
    assert is_local_or_private_host("127.0.0.1")
    assert is_local_or_private_host("10.0.0.5")
    assert is_local_or_private_host("172.16.0.1")
    assert is_local_or_private_host("192.168.1.10")
    assert is_local_or_private_host("::1")


def test_public_http_url_rejects_private_hosts_and_non_http():
    assert is_public_http_url("https://example.com/path")
    assert not is_public_http_url("http://127.0.0.1:8000/path")
    assert not is_public_http_url("file:///etc/passwd")
    assert not is_public_http_url("mailto:test@example.com")


def test_public_web_url_allows_external_websocket_only():
    assert is_public_web_url("wss://example.com/socket")
    assert not is_public_web_url("ws://localhost:8080/socket")


def test_safe_url_for_log_drops_sensitive_parts():
    assert safe_url_for_log("https://user:pass@example.com:8443/a?token=x#frag") == (
        "https://example.com:8443/a"
    )
    assert safe_url_for_log("file:///etc/passwd") == "file:<redacted>"
