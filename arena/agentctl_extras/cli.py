"""Dispatcher for agentctl_extras.py."""
from __future__ import annotations

import sys

from arena.agentctl_extras.actions import cmd_do, cmd_find, cmd_remember, cmd_tail
from arena.agentctl_extras.integrations import cmd_beep, cmd_mcp_install
from arena.agentctl_extras.maintenance import cmd_doctor_fix, cmd_update
from arena.agentctl_extras.status import cmd_ctx, run_status


CMDS = {
    "status": run_status,
    "ctx": cmd_ctx,
    "do": cmd_do,
    "tail": cmd_tail,
    "find": cmd_find,
    "remember": cmd_remember,
    "doctor-fix": cmd_doctor_fix,
    "update": cmd_update,
    "mcp-install": cmd_mcp_install,
    "beep": cmd_beep,
}


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    func = CMDS.get(cmd)
    if not func:
        print("Usage: agentctl_extras.py [" + "|".join(CMDS) + "] ...")
        return 2
    return int(func(sys.argv[2:]) or 0)
