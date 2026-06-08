"""Security primitives for the bridge: command blocklist, desktop-input-injection
detection (control-lease bypass guard), and SSRF URL validation.

These are pure, dependency-free (stdlib only) functions covered by
``tests/test_security.py``. They are imported and re-exported by
``unified_bridge.py`` for backward compatibility.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Desktop-input-injection patterns (control-lease bypass guard, v2.10.0)
#
# Patterns that indicate a shell command would inject desktop input
# (keyboard/mouse/touch). When control is paused/revoked these must be blocked
# even via /v1/exec, otherwise the pause lease can be trivially bypassed by
# shelling out to the same input tools the dedicated endpoints use.
# ---------------------------------------------------------------------------
_INPUT_INJECTION_PATTERNS = [
    r"\bydotool\b",
    r"\bwtype\b",
    r"\bdotoolc?\b",
    r"\bxdotool\b\s+[^|;&]*\b(key|keydown|keyup|type|click|mouse(move|down|up)?|windowactivate|windowfocus)\b",
    r"\bwlrctl\b",
    r"\bydotoold\b",
]


def _is_input_injection_cmd(cmd: str) -> str | None:
    """Return the matched pattern if cmd would inject desktop input, else None."""
    low = cmd.lower()
    for pat in _INPUT_INJECTION_PATTERNS:
        if re.search(pat, low, flags=re.I | re.S):
            return pat
    return None


# ---------------------------------------------------------------------------
# Command blocklist for /v1/exec
# ---------------------------------------------------------------------------
BLOCK_PATTERNS = [
    r"\brm\s+-[^\n]*[rf][^\n]*[rf][^\n]*(/|~|\*)",
    r"\bsudo\b",
    r"\bsu\b",
    r"\bmkfs(\.|\s|$)",
    r"\bdd\s+.*\bof\s*=\s*/dev/",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\bdiskpart\b",
    r"\bformat\s+[A-Za-z]:",
    r"\bbcdedit\b",
    r"\breg\s+delete\b",
    r"\btakeown\b",
    r"\bicacls\b.*\b/grant\b",
    r"\bchmod\s+-R\s+777\s+(/|~)",
    r"(curl|wget).*(\||>)\s*(sh|bash|zsh|fish|pwsh|powershell)",
    r"powershell(\.exe)?\s+.*-(enc|encodedcommand)\b",
    # v2.10.0: block access to well-known secret material
    r"(\.ssh/(id_[a-z0-9]+|identity)|/etc/shadow|\.gnupg/|\.netrc|\.git-credentials|\.aws/credentials|token\.txt)\b",
    # v2.10.0: block common reverse-shell patterns
    r"\bnc\b[^\n]*\s-e\b",
    r"\bncat\b[^\n]*\s-e\b",
    r"\b(bash|sh)\b\s+-i\b[^\n]*>&\s*/dev/tcp/",
    r"/dev/tcp/\d",
]


def blocked_reason(cmd: str) -> str | None:
    low = cmd.lower()
    for pat in BLOCK_PATTERNS:
        if re.search(pat, low, flags=re.I | re.S):
            return f"blocked by safety pattern: {pat}"
    return None


# Hostnames that should never be fetched through browser/read/fetch/head endpoints.
# These names commonly resolve to loopback/link-local metadata services, or are
# explicitly reserved for local-only name resolution.
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}


def _ip_is_blocked(addr: ipaddress._BaseAddress) -> bool:
    """Return True when an IP address is not safe for server-side fetching."""
    # Normalize IPv4-mapped IPv6 (::ffff:127.0.0.1) before classification.
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
    """Try hard to interpret a hostname as an IP address.

    Browsers and libc accept several IPv4 spellings that ``ipaddress`` does not
    parse directly, such as short dotted forms (``127.1``), octal dotted forms
    (``0177.0.0.1``), hexadecimal integers (``0x7f000001``), and decimal
    integers (``2130706433``). Treating those as ordinary hostnames creates SSRF
    bypasses, so normalize them before applying private/loopback checks.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass

    # Bare integer IPv4: decimal, hex, or legacy octal spelling.
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

    # Dotted short/octal/hex IPv4 variants. ``inet_aton`` intentionally accepts
    # these legacy forms, which is exactly what we need to classify them safely.
    parts = host.split(".")
    if 1 <= len(parts) <= 4 and all(
        re.fullmatch(r"0[xX][0-9a-fA-F]+|0[0-7]*|\d+", p) for p in parts
    ):
        try:
            return ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def _validate_url(url: str) -> str | None:
    """Validate URL scheme/host for browser endpoints.

    Returns ``None`` for allowed public HTTP(S) URLs, otherwise a short error
    string. This is a defense-in-depth SSRF guard; callers should still avoid
    sending secrets to fetched URLs and should prefer allowlists for production
    high-risk deployments.
    """
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

    # Defense in depth: resolve DNS now and reject any internal A/AAAA result.
    # This closes obvious metadata/localhost aliases and internal DNS records.
    # There remains a DNS-rebinding TOCTOU window because urllib will resolve
    # again during the fetch; fully eliminating that requires connecting to the
    # already-validated IP while preserving the original Host header.
    try:
        for _fam, _typ, _proto, _canon, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if _ip_is_blocked(ip):
                return "host resolves to a private/internal address"
    except (socket.gaierror, ValueError):
        # Let the actual fetch fail naturally for unresolved names.
        pass

    return None
