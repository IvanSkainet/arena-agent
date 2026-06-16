"""agentctl memory/recall commands."""
from __future__ import annotations

import json
import sys
from urllib.parse import quote

from arena.agentctl_cli.agentctl_common import bridge_get, bridge_post


def mem_set(args):
    if len(args) < 2:
        print("Usage: agentctl mem set KEY VALUE [--tags tag1 tag2]")
        sys.exit(2)
    key, value = args[0], args[1]
    tags = args[args.index("--tags") + 1:] if "--tags" in args else []
    try:
        r = bridge_post("/v1/memory", {"action": "set", "key": key, "value": value, "tags": tags})
        print(f"{'OK' if r.get('ok') else 'FAIL'}: {r}")
    except Exception as e:
        print(f"Error: {e}")


def mem_get(args):
    q = "" if args and args[0].lower() == "all" else (args[0] if args else "")
    try:
        r = bridge_get(f"/v1/memory?q={quote(q)}")
        print(f"Facts ({r.get('count',0)}):")
        for fact in r.get("facts", []):
            print(f"  {fact.get('key','?')}: {str(fact.get('value',''))[:80]}")
    except Exception as e:
        print(f"Error: {e}")


def recall_search(args):
    q = args[0] if args else ""
    try:
        r = bridge_get(f"/v1/recall?q={quote(q)}")
        print(f"Recall ({r.get('count',0)}):")
        for item in r.get("results", []):
            print(f"  [{item.get('score',0):.2f}] {item.get('key','?')}: {str(item.get('value',''))[:80]}")
    except Exception as e:
        print(f"Error: {e}")


def recall_digest(args):
    try:
        r = bridge_get("/v1/recall/digest")
        print(r.get("digest", json.dumps(r, indent=2, ensure_ascii=False)))
    except Exception as e:
        print(f"Error: {e}")
