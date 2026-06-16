"""agentctl audit/mission/report/subagent/mcp commands."""
from __future__ import annotations

import json

from arena.agentctl_cli.agentctl_common import ROOT, bridge_get, bridge_post, run_bin


def audit_stats(args):
    try:
        r = bridge_get("/v1/audit/stats")
        print(f"Total events: {r.get('total',0)}")
        for key, value in r.get("by_type", {}).items():
            print(f"  {key}: {value}")
    except Exception as e:
        print(f"Error: {e}")


def audit_tail(args):
    n = args[0] if args else "10"
    try:
        for line in bridge_get(f"/v1/audit?lines={n}").get("lines", [])[-int(n):]:
            print(line)
    except Exception as e:
        print(f"Error: {e}")


def backup_run(args):
    try:
        r = bridge_post("/v1/backup", {"paths": args if args else [str(ROOT)]})
        print(f"Backup: {r.get('ok')} files={r.get('file_count',0)} size={r.get('size',0)//1024}KB")
        print(f"Path: {r.get('backup_path','')}")
    except Exception as e:
        print(f"Error: {e}")


def mission_list(args):
    try:
        r = bridge_get("/v1/missions")
        print(f"Missions ({r.get('count',0)}):")
        for mission in r.get("missions", []):
            print(f"  {mission.get('name','?')}")
    except Exception as e:
        print(f"Error: {e}")


def report_list(args):
    try:
        print(json.dumps(bridge_get("/v1/reports"), indent=2, ensure_ascii=False)[:500])
    except Exception as e:
        print(f"Error: {e}")


def sub_spawn(args):
    run_bin("subagent.py", ["spawn"] + args)


def sub_list(args):
    run_bin("subagent.py", ["list"])


def mcp_install(args):
    run_bin("mcp_marketplace.py", ["install"] + args)


def mcp_list(args):
    run_bin("mcp_marketplace.py", ["list"])
