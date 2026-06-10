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

ROOT_DIR = Path(__file__).resolve().parent
BRIDGE_FILE = ROOT_DIR / "unified_bridge.py"
CONSTANTS_FILE = ROOT_DIR / "arena" / "constants.py"


def _extract_version_from(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("VERSION") and "=" in line:
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    return val
    except Exception:
        return None
    return None


def get_version() -> str:
    """Extract VERSION without importing bridge modules.

    Since v2.10.x the canonical version lives in arena/constants.py; older
    releases kept it in unified_bridge.py, so keep that as fallback.
    """
    return _extract_version_from(CONSTANTS_FILE) or _extract_version_from(BRIDGE_FILE) or "unknown"


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
