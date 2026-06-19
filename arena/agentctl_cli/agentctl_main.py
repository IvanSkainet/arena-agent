"""Main dispatcher for the agentctl CLI."""
from __future__ import annotations

import sys

from arena.agentctl_cli.agentctl_common import VERSION
from arena.agentctl_cli import agentctl_browser as browser
from arena.agentctl_cli import agentctl_browseract as bact
from arena.agentctl_cli import agentctl_memory as memory
from arena.agentctl_cli import agentctl_misc as misc
from arena.agentctl_cli import agentctl_skills as skills
from arena.agentctl_cli import agentctl_system as system
from arena.agentctl_cli import agentctl_tasks as tasks


def commands(args):
    print(f"""Arena Agent CLI v{VERSION} — Command Reference

Namespaces:
  sys     status|doctor|beep|svc|funnel|fix     System diagnostics
  mem     set|get                                Memory facts
  recall  search|digest                          TF-scored recall
  browser search|read|dump|head|shot             Browser tools
  bact    doctor|extract|shot|open|state|click|type|input|eval|close|auth|browsers|raw
                                                 BrowserAct stealth browser
  task    list|submit|clean                      Task queue
  skill   list|run                               Skills (executable + prompt-only)
  audit   stats|tail                             Audit log
  backup  run                                    Removed backup feature notice
  mission list                                   Missions
  report  list                                   Reports
  sub     spawn|list                             Subagents
  mcp     install|list                           MCP servers
  commands                                       This help

Usage: agentctl [namespace] [command] [args...]
Environment:
  ARENA_AGENT_HOME    Agent root directory (default: ~/arena-bridge)
  ARENA_BRIDGE_URL    Bridge URL (default: http://127.0.0.1:8765)
""")


DISPATCH = {
    "sys": {"status": system.status, "doctor": system.doctor, "beep": system.beep,
            "svc": system.svc, "funnel": system.funnel, "fix": system.fix},
    "mem": {"set": memory.mem_set, "get": memory.mem_get},
    "recall": {"search": memory.recall_search, "digest": memory.recall_digest},
    "browser": {"search": browser.search, "py-search": browser.search, "read": browser.read,
                "py-read": browser.read, "dump": browser.dump, "py-dump": browser.dump,
                "head": browser.head, "py-head": browser.head, "shot": browser.shot, "sd-shot": browser.shot},
    "bact": {name: bact.make_command(name) for name in ("doctor", "extract", "shot", "open", "state",
             "click", "type", "input", "eval", "close", "auth", "browsers", "raw")},
    "task": {"list": tasks.list_tasks, "ls": tasks.list_tasks, "submit": tasks.submit, "clean": tasks.clean},
    "skill": {"list": skills.list_skills, "ls": skills.list_skills, "run": skills.run_skill},
    "audit": {"stats": misc.audit_stats, "tail": misc.audit_tail},
    "backup": {"run": misc.backup_run},
    "mission": {"list": misc.mission_list, "ls": misc.mission_list},
    "report": {"list": misc.report_list, "ls": misc.report_list},
    "sub": {"spawn": misc.sub_spawn, "list": misc.sub_list},
    "mcp": {"install": misc.mcp_install, "list": misc.mcp_list},
    "commands": {"": commands},
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("h", "help", "--help", "-h"):
        commands([])
        sys.exit(0)
    ns = sys.argv[1].lower()
    args = sys.argv[2:]
    ns_map = DISPATCH.get(ns)
    if not ns_map:
        print(f"Unknown namespace: {ns}")
        print("Run: agentctl commands")
        sys.exit(2)
    sub = args[0].lower() if args else ""
    func = ns_map.get(sub)
    if not func:
        if ns_map:
            func = list(ns_map.values())[0]
            args = [sub] + args[1:]
        else:
            print(f"Unknown command: {ns} {sub}")
            sys.exit(2)
    try:
        func(args[1:] if sub else args)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
