"""agentctl system commands."""
from __future__ import annotations

import json
import sys

from arena.agentctl_cli.agentctl_common import bridge_get, bridge_post


def status(args):
    try:
        health = bridge_get("/health", token=False)
        info = bridge_get("/v1/sysinfo")
        funnel = bridge_get("/v1/sys/funnel")
        print(f"{'='*50}")
        print(f"Arena Unified Bridge v{health.get('version','?')}")
        print(f"{'='*50}")
        print(f"  Host:     {health.get('host','?')}")
        print(f"  Platform: {health.get('platform','?')}")
        print(f"  Profile:  {health.get('profile','?')}")
        print(f"  Root:     {health.get('root','?')}")
        print(f"  CPU:      {info.get('cpu_cores','?')} cores")
        print(f"  RAM:      {info.get('mem_total_mb',0)} MB total, {info.get('mem_avail_mb',0)} MB avail")
        print(f"  Disk:     {info.get('disk_free_gb',0)} GB free / {info.get('disk_total_gb',0)} GB total")
        print(f"  Uptime:   {health.get('uptime_seconds',0):.0f}s")
        ts = funnel.get("tailscale", {})
        if ts.get("connected"):
            print(f"  Tailscale: connected ({ts.get('status','')[:50]})")
        fn = funnel.get("funnel", {})
        if fn.get("active") is not False:
            print(f"  Funnel:   {fn.get('status','?')[:80]}")
        print(f"{'='*50}")
    except Exception as e:
        print(f"Error contacting bridge: {e}")
        sys.exit(1)


def doctor(args):
    try:
        d = bridge_get("/v1/doctor")
        print(f"\n{'='*50}")
        print(f"Doctor: {d.get('passed',0)}/{d.get('total',0)} checks passed")
        print(f"{'='*50}")
        for c in d.get("checks", []):
            icon = "✅" if c["ok"] else "❌"
            print(f"  {icon} {c['name']}: {c.get('detail','')}")
        print()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def beep(args):
    btype = args[0] if args else "success"
    try:
        r = bridge_post("/v1/beep", {"type": btype})
        print(f"Beep: {r.get('type','?')} freq={r.get('frequency','?')}Hz dur={r.get('duration','?')}ms")
    except Exception as e:
        print(f"Error: {e}")


def svc(args):
    try:
        print(json.dumps(bridge_get("/v1/sys/svc"), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")


def funnel(args):
    try:
        r = bridge_get("/v1/sys/funnel")
        print("Tailscale:", r.get("tailscale", {}).get("status", "unknown")[:200])
        print("Funnel:", r.get("funnel", {}).get("status", "unknown")[:200])
    except Exception as e:
        print(f"Error: {e}")


def fix(args):
    print("Auto-fix not yet implemented in unified bridge. Use: agentctl sys doctor")
