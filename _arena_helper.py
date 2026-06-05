#!/usr/bin/env python3
"""Arena Unified Bridge — Installer Helper.

Utility functions for the installer scripts (version detection, token generation).
Can be called from install.bat / install.sh via:
    python _arena_helper.py version   — print the bridge version
    python _arena_helper.py token     — generate a new auth token
"""
import sys
import secrets
from pathlib import Path

BRIDGE_FILE = Path(__file__).resolve().parent / "unified_bridge.py"


def get_version() -> str:
    """Extract VERSION from unified_bridge.py without importing it."""
    try:
        text = BRIDGE_FILE.read_text(encoding="utf-8")
        idx = text.find('VERSION = ')
        if idx < 0:
            return "unknown"
        q1 = text.find('"', idx) + 1
        q2 = text.find('"', q1)
        if q1 > 0 and q2 > 0:
            return text[q1:q2]
    except Exception:
        pass
    return "unknown"


def generate_token(nbytes: int = 32) -> str:
    """Generate a URL-safe base64 token."""
    return secrets.token_urlsafe(nbytes)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} version|token", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "version":
        print(get_version())
    elif cmd == "token":
        print(generate_token())
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
