#!/usr/bin/env python3
"""skill_from_sub.py — превратить успешный subagent в multipurpose skill.

Идея (от Hermes self-skills): если sub-agent отработал ok, и его команда полезна,
сохраняем её как skill — чтобы переиспользовать без переписывания.

Usage:
  skill_from_sub.py <subagent_id> <skill_name>
                    [--desc "..."] [--mode safe|edit|full]

Skill ляжет в ~/arena-agent/skills/auto/<skill_name>/ — SKILL.md, manifest.json, run.sh.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-agent"))).expanduser()
SUB = ROOT / "subagents"
SK = ROOT / "skills" / "auto"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sub_id")
    ap.add_argument("name")
    ap.add_argument("--desc", default="")
    ap.add_argument("--mode", default="safe", choices=("safe", "edit", "full"))
    a = ap.parse_args()

    sub_dir = SUB / a.sub_id
    meta_p = sub_dir / "meta.json"
    summary_p = sub_dir / "summary.json"
    if not meta_p.exists():
        print(f"ERR: no such subagent: {a.sub_id}", file=sys.stderr); return 1
    meta = json.loads(meta_p.read_text())
    summary = json.loads(summary_p.read_text()) if summary_p.exists() else {}
    cmd = meta.get("cmd", "")
    if not cmd:
        print("ERR: subagent has no cmd", file=sys.stderr); return 1
    if summary.get("status") not in ("ok", "spawned"):
        print(f"WARN: subagent status={summary.get('status')}; saving anyway", file=sys.stderr)

    target = SK / a.name
    if target.exists():
        print(f"ERR: skill already exists: {target}", file=sys.stderr); return 1
    target.mkdir(parents=True, exist_ok=False)

    desc = a.desc or f"Auto-generated from subagent {a.sub_id} ({meta.get('name','')})"
    (target / "SKILL.md").write_text(
        f"""# auto/{a.name}

{desc}

## Inputs
- argv[*]: passed to the underlying command

## Outputs
- whatever the original command produced

## Provenance
- Generated from subagent: `{a.sub_id}`
- Original cmd: `{cmd}`
- Mode: `{a.mode}`
""")
    (target / "manifest.json").write_text(json.dumps({
        "name": f"auto/{a.name}", "description": desc,
        "args": [], "timeout": int(meta.get("timeout", 300)), "mode": a.mode,
        "provenance": {"subagent_id": a.sub_id, "original_cmd": cmd},
    }, ensure_ascii=False, indent=2))
    # run.sh — оборачиваем команду, прокидываем "$@"
    run = target / "run.sh"
    run.write_text(f"""#!/usr/bin/env bash
# auto-generated from subagent {a.sub_id}
set -euo pipefail
{cmd} "$@"
""")
    run.chmod(0o755)

    print(json.dumps({"ok": True, "skill": f"auto/{a.name}", "path": str(target),
                      "run": f"agentctl skill run auto/{a.name}"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
