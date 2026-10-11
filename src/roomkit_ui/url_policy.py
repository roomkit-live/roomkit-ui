"""URL policy helpers for embedded, server-provided UI content.

A host is public only if every address it stands for is globally routable.
Three ways around a hostname-only check are closed here:

* a numeric IPv4 form a browser accepts but ``ipaddress`` does not
  (``2130706433``, ``127.1``, ``0x7f.1``) — parsed the way the WHATWG URL
  standard says, so it is judged as the address the browser will dial;
* a public name that resolves to a private address (``localtest.me``,
  ``127.0.0.1.nip.io``) — names are resolved and every address checked;
* address space ``is_private`` misses (100.64.0.0/10, NAT64, 6to4) —
  ``not is_global`` decides, with the embedded IPv4 checked where there is one.

DNS rebinding (a name that resolves publicly here and privately a moment
later, when the browser connects) is not closed by a check made before the
connection; the MCP App view relies on the browser's same-origin policy for
that (see ``widgets/mcp_app_widget.py``).
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from urllib.parse import urlparse, urlsplit, urlunparse, urlunsplit

_PUBLIC_WEB_SCHEMES = {"http", "https", "ws", "wss"}

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_NAT64 = ipaddress.ip_network("64:ff9b::/96")

# A slow resolver must not freeze the UI thread the checks run on; an
# unanswered name is refused, not waved through.
_RESOLVE_TIMEOUT = 2.0
_RESOLVE_CACHE_TTL = 60.0
_resolve_cache: dict[str, tuple[float, bool]] = {}
_resolve_lock = threading.Lock()
_resolver = ThreadPoolExecutor(max_workers=4, thread_name_prefix="url-policy-dns")


class _InvalidHostError(ValueError):
    """A host a browser would refuse to parse (e.g. ``1.2.3.4.5``)."""


def parse_ipv4_like_browser(host: str) -> ipaddress.IPv4Address | None:
    """Return the IPv4 address a browser reads in *host*, None for a name.

    WHATWG URL "IPv4 parser": a host whose last label is a number is an
    address — up to four parts, each decimal, ``0x`` hex or ``0`` octal, the
    last filling the remaining bytes. Raises ``_InvalidHostError`` for a host
    that ends in a number yet is not a valid address: browsers reject it too.
    """
    parts = host.split(".")
    if parts and parts[-1] == "":
        parts.pop()
    if not parts or not _is_ipv4_number(parts[-1]):
        return None
    if len(parts) > 4:
        raise _InvalidHostError(host)
    numbers = [_ipv4_number(part, host) for part in parts]
    if any(n > 255 for n in numbers[:-1]) or numbers[-1] >= 256 ** (5 - len(numbers)):
        raise _InvalidHostError(host)
    value = numbers[-1]
    for index, number in enumerate(numbers[:-1]):
        value += number * 256 ** (3 - index)
    return ipaddress.IPv4Address(value)


def _is_ipv4_number(part: str) -> bool:
    if part.isdigit():
        return True
    return part[:2] in ("0x", "0X") and all(c in "0123456789abcdefABCDEF" for c in part[2:])


def _ipv4_number(part: str, host: str) -> int:
    try:
        if part[:2] in ("0x", "0X"):
            return int(part[2:] or "0", 16)
        if len(part) > 1 and part.startswith("0"):
            return int(part[1:], 8)
        return int(part, 10)
    except ValueError:
        raise _InvalidHostError(host) from None


def is_global_address(ip: IPAddress) -> bool:
    """True for a globally routable unicast address, judged on its IPv4 part
    when it embeds one (IPv4-mapped, NAT64, 6to4)."""
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None:
            return is_global_address(embedded)
    return ip.is_global and not ip.is_multicast


def _literal_address(host: str) -> IPAddress | None:
    """The address *host* spells out, None for a name; raises for junk."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    return parse_ipv4_like_browser(host)


def is_local_or_private_host(host: str | None) -> bool:
    """Return True for hosts that are, or spell, a non-public address.

    Names are not resolved here — see ``host_is_public``.
    """
    if not host:
        return True
    normalized = host.strip().strip("[]").lower().rstrip(".")
    if not normalized or normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        ip = _literal_address(normalized)
    except _InvalidHostError:
        return True
    return ip is not None and not is_global_address(ip)


def host_is_public(host: str | None) -> bool:
    """True when *host* is public and, for a name, every address it resolves
    to is too. A name that does not resolve (in time) is not public."""
    if not host or is_local_or_private_host(host):
        return False
    normalized = host.strip().strip("[]").lower().rstrip(".")
    if _literal_address(normalized) is not None:
        return True
    return _resolves_to_public_only(normalized)


def _resolves_to_public_only(name: str) -> bool:
    """Resolve *name*, cached for a minute; a failed lookup is not cached."""
    now = time.monotonic()
    with _resolve_lock:
        cached = _resolve_cache.get(name)
    if cached is not None and cached[0] > now:
        return cached[1]
    try:
        addresses = _resolver.submit(_resolve, name).result(timeout=_RESOLVE_TIMEOUT)
    except (FutureTimeout, OSError, UnicodeError, ValueError):
        return False
    verdict = bool(addresses) and all(is_global_address(ip) for ip in addresses)
    with _resolve_lock:
        _resolve_cache[name] = (now + _RESOLVE_CACHE_TTL, verdict)
    return verdict


def _resolve(name: str) -> list[IPAddress]:
    """Every address *name* resolves to. Tests replace this."""
    infos = socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)
    return [ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in infos]


def clear_resolve_cache() -> None:
    """Forget cached resolutions (tests)."""
    with _resolve_lock:
        _resolve_cache.clear()


def is_public_http_url(url: str) -> bool:
    """Return True for HTTP(S) URLs whose host is public (resolved)."""
    return public_http_url(url) is not None


def public_http_url(url: str) -> str | None:
    """Return *url* rebuilt from what was checked, or None if it is not public.

    The caller opens the returned string, not the original: a parser
    differential (``http://127.0.0.1\\@example.com/`` is example.com to
    ``urlsplit`` and 127.0.0.1 to a browser) cannot then smuggle in another
    host, because the user info it hides in is dropped. Whitespace and
    control characters are refused outright.
    """
    if any(c.isspace() or ord(c) < 0x20 or c == "\x7f" for c in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not host_is_public(parts.hostname):
        return None
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def is_public_web_url(url: str) -> bool:
    """Return True for public HTTP(S)/WS(S) network requests (host resolved)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in _PUBLIC_WEB_SCHEMES and host_is_public(parts.hostname)


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
