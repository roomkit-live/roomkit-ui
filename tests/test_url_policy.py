import ipaddress
import time

import pytest

import roomkit_ui.url_policy as url_policy
from roomkit_ui.url_policy import (
    host_is_public,
    is_local_or_private_host,
    is_public_http_url,
    is_public_web_url,
    parse_ipv4_like_browser,
    public_http_url,
    safe_url_for_log,
)

# What names resolve to in these tests — no real DNS.
_DNS = {
    "example.com": ["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"],
    "localtest.me": ["127.0.0.1", "::1"],
    "127.0.0.1.nip.io": ["127.0.0.1"],
    "split.example": ["93.184.215.14", "10.0.0.7"],
    "cgnat.example": ["100.64.1.2"],
}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    def resolve(name):
        if name not in _DNS:
            raise OSError(f"no such host: {name}")
        return [ipaddress.ip_address(a) for a in _DNS[name]]

    monkeypatch.setattr(url_policy, "_resolve", resolve)
    url_policy.clear_resolve_cache()
    yield
    url_policy.clear_resolve_cache()


def test_local_or_private_hosts_are_blocked():
    assert is_local_or_private_host("localhost")
    assert is_local_or_private_host("app.localhost")
    assert is_local_or_private_host("127.0.0.1")
    assert is_local_or_private_host("10.0.0.5")
    assert is_local_or_private_host("172.16.0.1")
    assert is_local_or_private_host("192.168.1.10")
    assert is_local_or_private_host("::1")


@pytest.mark.parametrize(
    "host",
    [
        "100.64.0.1",  # shared address space (CGNAT): not is_private, not global
        "169.254.169.254",  # cloud metadata
        "0.0.0.0",
        "::ffff:127.0.0.1",  # IPv4-mapped
        "64:ff9b::7f00:1",  # NAT64 of 127.0.0.1
        "2002:7f00:1::",  # 6to4 of 127.0.0.1
        "224.0.0.1",  # multicast
    ],
)
def test_non_global_address_space_is_blocked(host):
    assert is_local_or_private_host(host)


@pytest.mark.parametrize(
    ("host", "address"),
    [
        ("2130706433", "127.0.0.1"),
        ("127.1", "127.0.0.1"),
        ("0x7f.1", "127.0.0.1"),
        ("0177.0.0.1", "127.0.0.1"),
        ("0x7f000001", "127.0.0.1"),
        ("10.1", "10.0.0.1"),
        ("127.0.0.1.", "127.0.0.1"),
    ],
)
def test_numeric_ipv4_forms_read_as_the_browser_reads_them(host, address):
    assert parse_ipv4_like_browser(host) == ipaddress.IPv4Address(address)
    assert is_local_or_private_host(host)


def test_a_host_ending_in_a_number_that_no_browser_accepts_is_blocked():
    assert is_local_or_private_host("1.2.3.4.5")
    assert is_local_or_private_host("example.123")
    assert is_local_or_private_host("256.256.256.256")


def test_names_are_judged_on_every_address_they_resolve_to():
    assert host_is_public("example.com")
    assert not host_is_public("localtest.me")
    assert not host_is_public("127.0.0.1.nip.io")
    assert not host_is_public("split.example")  # one private address is enough
    assert not host_is_public("cgnat.example")
    assert not host_is_public("unresolvable.example")


def test_a_resolver_that_hangs_refuses_instead_of_freezing(monkeypatch):
    monkeypatch.setattr(url_policy, "_RESOLVE_TIMEOUT", 0.2)
    monkeypatch.setattr(url_policy, "_resolve", lambda name: time.sleep(2) or [])

    started = time.monotonic()
    assert not host_is_public("slow.example")
    assert time.monotonic() - started < 1


def test_public_http_url_rejects_private_hosts_and_non_http():
    assert is_public_http_url("https://example.com/path")
    assert not is_public_http_url("http://127.0.0.1:8000/path")
    assert not is_public_http_url("http://2130706433/")
    assert not is_public_http_url("http://127.1/")
    assert not is_public_http_url("http://localtest.me/")
    assert not is_public_http_url("file:///etc/passwd")
    assert not is_public_http_url("mailto:test@example.com")


def test_public_http_url_returns_what_it_checked_not_what_it_was_given():
    # urlsplit reads example.com here, a browser 127.0.0.1: the user info that
    # hides the difference is dropped from the URL that gets opened.
    assert public_http_url("http://127.0.0.1\\@example.com/x?q=1#f") == (
        "http://example.com/x?q=1#f"
    )
    assert public_http_url("https://user:pw@example.com:8443/a") == "https://example.com:8443/a"
    assert public_http_url("https://example.com/a b") is None
    assert public_http_url("https://example.com/\tx") is None
    assert public_http_url("https://example.com:99999/") is None


def test_public_web_url_allows_external_websocket_only():
    assert is_public_web_url("wss://example.com/socket")
    assert not is_public_web_url("ws://localhost:8080/socket")
    assert not is_public_web_url("wss://127.0.0.1.nip.io/socket")


def test_safe_url_for_log_drops_sensitive_parts():
    assert safe_url_for_log("https://user:pass@example.com:8443/a?token=x#frag") == (
        "https://example.com:8443/a"
    )
    assert safe_url_for_log("file:///etc/passwd") == "file:<redacted>"
