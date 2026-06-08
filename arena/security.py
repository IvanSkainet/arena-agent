"""Security primitives for the bridge: command blocklist, desktop-input-injection
detection (control-lease bypass guard), and SSRF URL validation.

These are pure, dependency-free (stdlib only) functions covered by
``tests/test_security.py``. They are imported and re-exported by
``unified_bridge.py`` for backward compatibility.
"""
from __future__ import annotations

import ipaddress
import re
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


def _validate_url(url: str) -> str | None:
    """Validate URL scheme for browser endpoints. Returns error message or None."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "invalid URL"
    if parsed.scheme not in ("http", "https"):
        return f"URL scheme '{parsed.scheme}' not allowed (only http/https)"
    hostname = parsed.hostname or ""
    # Block localhost / loopback
    if hostname in ("localhost", "0.0.0.0", "::1", "::"):
        return "localhost/internal URLs not allowed"
    # Block private/reserved IPs using ipaddress module
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return "private/internal URLs not allowed"
    except ValueError:
        pass  # hostname, not IP — continue with string checks
    # Block cloud metadata
    if hostname.startswith("169.254."):
        return "cloud metadata URLs not allowed"
    return None
