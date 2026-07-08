"""URL policy helpers for embedded, server-provided UI content."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse, urlunparse

_PUBLIC_WEB_SCHEMES = {"http", "https", "ws", "wss"}


def is_local_or_private_host(host: str | None) -> bool:
    """Return True for hostnames/IPs that target local or private networks."""
    if not host:
        return True
    normalized = host.strip().strip("[]").lower().rstrip(".")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return any(
        (
            ip.is_loopback,
            ip.is_private,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_unspecified,
            ip.is_reserved,
        )
    )


def is_public_http_url(url: str) -> bool:
    """Return True for HTTP(S) URLs that do not target local/private hosts."""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and not is_local_or_private_host(parsed.hostname)


def is_public_web_url(url: str) -> bool:
    """Return True for public HTTP(S)/WS(S) network requests."""
    parsed = urlparse(url)
    return parsed.scheme in _PUBLIC_WEB_SCHEMES and not is_local_or_private_host(parsed.hostname)


def safe_url_for_log(url: str) -> str:
    """Return a URL without query/fragment/userinfo for logs."""
    parsed = urlparse(url)
    if not parsed.scheme:
        return "<missing-scheme>"
    if parsed.scheme not in _PUBLIC_WEB_SCHEMES:
        return f"{parsed.scheme}:<redacted>"
    netloc = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
