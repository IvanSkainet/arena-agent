#!/usr/bin/env python3
"""
Arena installer helper.
Used by install.bat / install.sh / update.bat / update.sh to avoid
embedding fragile inline Python in shell scripts.

Usage:
    python _arena_helper.py version <path-to-unified_bridge.py>
    python _arena_helper.py gentoken
    python _arena_helper.py info
"""
import sys
import os
import re
import secrets
import base64
import platform
import json


def cmd_version(path):
    if not path or not os.path.exists(path):
        print("missing")
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            t = f.read()
        m = re.search(r'VERSION\s*=\s*[\'"]([^\'"]+)[\'"]', t)
        print(m.group(1) if m else "unknown")
        return 0
    except Exception as e:
        print("error:" + str(e))
        return 1


def cmd_gentoken():
    print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))
    return 0


def cmd_info():
    print(json.dumps({
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
    }, indent=2))
    return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: _arena_helper.py {version <path> | gentoken | info}",
              file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    if cmd == "version":
        return cmd_version(sys.argv[2] if len(sys.argv) > 2 else "")
    if cmd == "gentoken":
        return cmd_gentoken()
    if cmd == "info":
        return cmd_info()
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
