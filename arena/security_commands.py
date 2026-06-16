"""Command blocklist for /v1/exec."""
from __future__ import annotations

import re

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
    r"(\.ssh/(id_[a-z0-9]+|identity)|/etc/shadow|\.gnupg/|\.netrc|\.git-credentials|\.aws/credentials|token\.txt)\b",
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
