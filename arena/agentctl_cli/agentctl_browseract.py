"""agentctl BrowserAct commands."""
from __future__ import annotations

import sys

from arena.agentctl_cli.agentctl_common import bridge_post


def run_browseract(subcmd, args):
    try:
        r = bridge_post("/v1/skills/run", {"name": "browseract", "args": [subcmd] + list(args)})
        print(r.get("output", "") or r.get("stdout", ""), end="")
        if r.get("stderr"):
            print(r.get("stderr"), end="", file=sys.stderr)
        if not r.get("ok"):
            sys.exit(r.get("exit_code", 1))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def make_command(subcmd: str):
    return lambda args: run_browseract(subcmd, args)
