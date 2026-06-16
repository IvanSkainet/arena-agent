"""agentctl task commands."""
from __future__ import annotations

import sys

from arena.agentctl_cli.agentctl_common import bridge_get, bridge_post


def list_tasks(args):
    try:
        r = bridge_get("/v1/tasks")
        print(f"Tasks ({r.get('count',0)}):")
        for task in r.get("tasks", []):
            print(f"  [{task.get('state','?')}] {task.get('id','?')} {task.get('cmd','')[:60]}")
    except Exception as e:
        print(f"Error: {e}")


def submit(args):
    if not args:
        print("Usage: agentctl task submit CMD")
        sys.exit(2)
    try:
        r = bridge_post("/v1/tasks", {"cmd": " ".join(args)})
        print(f"Submitted: {r.get('id','?')} {r.get('state','?')}")
    except Exception as e:
        print(f"Error: {e}")


def clean(args):
    try:
        print(f"Cleaned: {bridge_post('/v1/tasks/clean', {})}")
    except Exception as e:
        print(f"Error: {e}")
