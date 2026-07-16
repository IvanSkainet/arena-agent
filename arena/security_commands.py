"""Command blocklist for /v1/exec.

Design principles (v4.0.1):

1. **Non-interactive sudo is allowed.** Blocking every ``sudo`` invocation
   prevents agents from doing legitimate work (``sudo -n systemctl status``,
   ``sudo setcap`` in privileged inventory probes, ``sudo -n -u other id``).
   The wrapper only blocks INTERACTIVE sudo (``sudo`` without any flag, or
   ``sudo -S`` which reads a password from stdin) and ``sudo -i``/``sudo -s``
   (open a root shell). Non-interactive forms (``sudo -n ...``, ``sudo -k``,
   ``sudo -v -n``) and target-user forms (``sudo -u user cmd``) fall through
   to the OS which either succeeds via NOPASSWD sudoers or fails cleanly.

2. **Destructive real-name commands stay blocked.** ``rm -rf /``,
   ``mkfs``, ``dd if=... of=/dev/...``, Windows ``format C:``, etc.
   remain flat-out banned because a rogue prompt can spell them
   verbatim and no legitimate agent workflow needs them at the CLI.

3. **Credentials access stays blocked.** ``.ssh/id_*``, ``.gnupg``,
   ``/etc/shadow``, ``.aws/credentials`` etc. must not appear as CLI
   arguments — agents should use the dedicated /v1/fs/view endpoint
   which respects the sandbox root and doesn't get logged in shell
   history.
"""
from __future__ import annotations

import re

BLOCK_PATTERNS: list[str] = [
    # Destructive `rm -rf` against absolute paths, home directory,
    # or wildcards. `rm -rf ./tmp/build` and `rm -rf tmp/build` (both
    # relative) are legitimate and left alone.
    r"\brm\s+[-\w]*[rf][-\w]*[rf][-\w]*\s+(?:-[-\w]+\s+)*(?:/|~|\*(?:$|\s|[^\w])|(?:\.{1,2}/)+\*)",

    # Interactive sudo forms only. `\bsudo\b` alone was too aggressive
    # (blocked `sudo -n status`); this pattern targets the shapes that
    # actually put a root shell in front of the agent:
    #
    #     sudo -i        -> interactive login shell
    #     sudo -s        -> interactive shell
    #     sudo -S ...    -> read password from stdin (script-friendly, but
    #                       needs credentials the bridge shouldn't handle)
    #     sudo su        -> shell escalation
    #     sudo bash|sh|zsh|fish|pwsh (without further args)
    #     su             -> interactive switch
    #
    # Passwordless non-interactive sudo (``sudo -n cmd``, ``sudo -k``,
    # ``sudo -u user cmd``) is left alone -- if the operator configured
    # NOPASSWD in sudoers, that's a deliberate policy decision.
    r"(?:^|[\s;&|`(])sudo\s+(?:-i\b|-s\b|-S\b|su\b|(?:ba|z|fi)?sh\b(?!\s+-c\s)|pwsh\b|powershell\b)",
    r"(?:^|[\s;&|`(])su\s+(?:-\s*$|-\s+[\w-]|$|\s*$)",

    # Filesystem destroyers.
    r"\bmkfs(\.|\s|$)",
    r"\bdd\s+.*\bof\s*=\s*/dev/",
    r"\bshred\s+.*(/|~)",

    # Whole-system shutdown/reboot.
    r"\bshutdown\s+(?:-h|-r|-P|now\b)",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",

    # Windows destructive.
    r"\bdiskpart\b",
    r"\bformat\s+[A-Za-z]:",
    r"\bbcdedit\b",
    r"\breg\s+delete\b\s+HKLM\\",
    r"\btakeown\b",
    r"\bicacls\b[^\n]*\b/grant\b[^\n]*Everyone",

    # World-writable permission catastrophes on system paths.
    r"\bchmod\s+-R\s+777\s+(/|~)",

    # curl|bash and similar remote-code-execution shell-outs.
    r"(curl|wget)[^\n|;]*(\||>)\s*(?:sudo\s+)?(sh|bash|zsh|fish|pwsh|powershell)\b",

    # PowerShell -EncodedCommand hides intent — block.
    r"powershell(\.exe)?\s+[^\n]*-(enc|encodedcommand)\b",

    # Credentials access via CLI. Agents must use /v1/fs/view for
    # legitimate needs (which the sandbox controls).
    r"(?:^|[\s;&|`(])(?:cat|less|more|head|tail|bat|xxd|hexdump)\s+[^\n;|&]*"
    r"(?:\.ssh/(?:id_[a-z0-9]+|identity)|/etc/shadow|\.gnupg/|"
    r"\.netrc|\.git-credentials|\.aws/credentials|token\.txt)",

    # Reverse shells over /dev/tcp.
    r"\bnc\b[^\n]*\s-e\b",
    r"\bncat\b[^\n]*\s-e\b",
    r"\b(bash|sh)\b\s+-i\b[^\n]*>&\s*/dev/tcp/",
    r"/dev/tcp/\d",
]


def blocked_reason(cmd: str) -> str | None:
    """Return a short human-readable reason if ``cmd`` matches a block
    pattern, else ``None``. Case-insensitive."""
    for pat in BLOCK_PATTERNS:
        if re.search(pat, cmd, flags=re.I | re.S):
            return f"blocked by safety pattern: {pat}"
    return None
