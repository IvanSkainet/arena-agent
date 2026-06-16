"""SSRF URL validation for browser/fetch endpoints."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}


def _ip_is_blocked(addr: ipaddress._BaseAddress) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _coerce_ip(host: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass

    try:
        if re.fullmatch(r"0[xX][0-9a-fA-F]+|0[0-7]*|\d+", host):
            if host.lower().startswith("0x"):
                n = int(host, 16)
            elif len(host) > 1 and host.startswith("0"):
                n = int(host, 8)
            else:
                n = int(host, 10)
            if 0 <= n <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(n)
    except ValueError:
        pass

    parts = host.split(".")
    if 1 <= len(parts) <= 4 and all(re.fullmatch(r"0[xX][0-9a-fA-F]+|0[0-7]*|\d+", p) for p in parts):
        try:
            return ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def _validate_url(url: str) -> str | None:
    """Validate URL scheme/host for browser endpoints."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "invalid URL"

    if parsed.scheme not in ("http", "https"):
        return f"URL scheme '{parsed.scheme}' not allowed (only http/https)"

    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host:
        return "missing host"

    if (
        host in _BLOCKED_HOSTNAMES
        or host.endswith(".localhost")
        or host.endswith(".localdomain")
        or host.endswith(".internal")
        or host.endswith(".local")
    ):
        return "internal/metadata hostname not allowed"

    coerced = _coerce_ip(host)
    if coerced is not None and _ip_is_blocked(coerced):
        return "private/internal address not allowed"

    try:
        for _fam, _typ, _proto, _canon, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if _ip_is_blocked(ip):
                return "host resolves to a private/internal address"
    except (socket.gaierror, ValueError):
        pass

    return None
