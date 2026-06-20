"""agentctl memory/recall commands."""
from __future__ import annotations

import json
import sys
from urllib.parse import quote

from arena.agentctl_cli.agentctl_common import bridge_get, bridge_post


def _arg_value(args: list[str], name: str) -> str | None:
    if name in args:
        idx = args.index(name)
        if idx + 1 < len(args):
            return args[idx + 1]
    return None


def _remove_flag(args: list[str], name: str) -> list[str]:
    if name not in args:
        return list(args)
    idx = args.index(name)
    end = min(len(args), idx + 2)
    return args[:idx] + args[end:]


def mem_set(args):
    if len(args) < 2:
        print("Usage: agentctl mem set KEY VALUE [--tags tag1 tag2] [--profile PROFILE]")
        sys.exit(2)
    profile = _arg_value(args, "--profile") or "default"
    clean_args = _remove_flag(args, "--profile")
    key, value = clean_args[0], clean_args[1]
    tags = clean_args[clean_args.index("--tags") + 1:] if "--tags" in clean_args else []
    try:
        r = bridge_post("/v1/memory", {"profile": profile, "key": key, "value": value, "tags": tags})
        print(f"{'OK' if r.get('ok') else 'FAIL'}: {r}")
    except Exception as e:
        print(f"Error: {e}")


def mem_get(args):
    profile = _arg_value(args, "--profile") or "default"
    clean_args = _remove_flag(args, "--profile")
    q = "" if clean_args and clean_args[0].lower() == "all" else (clean_args[0] if clean_args else "")
    try:
        r = bridge_get(f"/v1/memory?profile={quote(profile)}&q={quote(q)}")
        print(f"Facts ({r.get('count',0)}) in profile {r.get('profile','default')}:")
        for fact in r.get("facts", []):
            print(f"  {fact.get('key','?')}: {str(fact.get('value',''))[:80]}")
    except Exception as e:
        print(f"Error: {e}")


def recall_search(args):
    profile = _arg_value(args, "--profile") or "default"
    clean_args = _remove_flag(args, "--profile")
    q = clean_args[0] if clean_args else ""
    try:
        r = bridge_get(f"/v1/recall?profile={quote(profile)}&q={quote(q)}")
        print(f"Recall ({r.get('count',0)}) in profile {r.get('profile','default')}:")
        for item in r.get("facts", []):
            fact = item.get("fact", item)
            print(f"  [{item.get('score',0):.2f}] {fact.get('key','?')}: {str(fact.get('value',''))[:80]}")
    except Exception as e:
        print(f"Error: {e}")


def recall_digest(args):
    profile = _arg_value(args, "--profile") or "default"
    try:
        r = bridge_get(f"/v1/recall/digest?profile={quote(profile)}")
        print(r.get("digest", json.dumps(r, indent=2, ensure_ascii=False)))
    except Exception as e:
        print(f"Error: {e}")
