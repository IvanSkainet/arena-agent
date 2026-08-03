"""SSRF URL validation for browser/fetch endpoints."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

# The private base `ipaddress._BaseAddress` does NOT declare is_private /
# is_loopback / ... -- those live on the concrete classes. Annotating against
# it made the checker right and the code merely lucky; the public union says
# exactly what `ip_address()` returns.
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}


def _ip_is_blocked(addr: IPAddress) -> bool:
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


def _looks_numeric_host(host: str) -> bool:
    """True for a host made only of numeric components (no letters at all).

    Such a string is always an attempt to write an ADDRESS -- a real hostname
    cannot be all-numeric under RFC 1123's final-label rule -- so if it did
    not decode to a valid one, it is malformed rather than a name to resolve.
    """
    parts = host.split(".")
    return bool(parts) and all(
        re.fullmatch(r"0[xX][0-9a-fA-F]+|0[0-7]*|\d+", p) for p in parts)


def _components_fit_ipv4(parts: list[str]) -> bool:
    """True when every dotted component is in range for `inet_aton`.

    `inet_aton` reads the LAST component as the remaining bytes, so the bound
    depends on how many parts there are: `1.2.3.4` caps each at 255, while a
    bare `2130706433` may use the full 32 bits. Anything above its own bound
    is an overflow that BSD would wrap and glibc would refuse; we refuse it
    on every platform so the verdict does not depend on the C library.
    """
    for index, part in enumerate(parts):
        try:
            if part.lower().startswith("0x"):
                value = int(part, 16)
            elif len(part) > 1 and part.startswith("0"):
                value = int(part, 8)
            else:
                value = int(part, 10)
        except ValueError:
            return False
        last = index == len(parts) - 1
        limit = (1 << (8 * (4 - len(parts) + 1))) - 1 if last else 0xFF
        if not 0 <= value <= limit:
            return False
    return True


def _coerce_ip(host: str) -> IPAddress | None:
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
        # `inet_aton` accepts spellings the branch above does not (short forms
        # like `127.1`, mixed radixes). It is also libc-dependent on overflow:
        # glibc rejects a value above 2**32, BSD/macOS silently TRUNCATES it
        # to the low 32 bits. That difference is a parser differential, not a
        # curiosity -- on macOS `http://99999999999999/` used to pass
        # validation (the branch above bails on `n > 0xFFFFFFFF`, and this one
        # decoded 16.122.63.255, a routable address), while the HTTP client,
        # sharing the same libc, would then connect to 16.122.63.255. The
        # reviewer and the socket saw different hosts.
        #
        # So: reject anything a component of which does not fit, instead of
        # letting libc decide what wrapping means.
        if not _components_fit_ipv4(parts):
            return None
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

    # An all-numeric host that `_coerce_ip` refused is an out-of-range address
    # spelling, not a hostname. Letting it through would hand the decision to
    # libc: glibc's getaddrinfo says NXDOMAIN, BSD's inet_aton truncates to
    # the low 32 bits and connects somewhere else entirely. Refuse it here so
    # the validator's verdict does not depend on the platform.
    if coerced is None and _looks_numeric_host(host):
        return "malformed numeric address not allowed"

    try:
        for _fam, _typ, _proto, _canon, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if _ip_is_blocked(ip):
                return "host resolves to a private/internal address"
    except (socket.gaierror, ValueError):
        pass

    return None
