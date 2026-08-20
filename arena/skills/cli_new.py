"""Skill scaffolding command."""
from __future__ import annotations

from arena.skills.cli_common import SK, json, sys

SKILL_TEMPLATE_MD = """# {name}

One-line purpose: TODO.

## Inputs
- argv: TODO

## Outputs
- TODO (stdout, files in reports/, memory facts, ...)

## Notes
TODO
"""

RUN_PY_TEMPLATE = '''#!/usr/bin/env python3
"""Entry point for the {name} skill.

Scaffolded as run.py rather than run.sh: Windows is a supported platform and
has no bash on PATH by default, so a shell runner fails out of the box (#126).

Available env: ARENA_AGENT_HOME, SKILL_NAME, SKILL_DIR, SKILL_ARGS (JSON).
"""
from __future__ import annotations

import os
import sys


def main(argv: list[str]) -> int:
    name = os.environ.get("SKILL_NAME", "{name}")
    print(f"skill {{name}} running with args: {{' '.join(argv)}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''

MANIFEST_TEMPLATE = {
    "name": "",
    "description": "",
    "args": [],
    "timeout": 300,
    "mode": "safe",
}

def new_skill(args) -> int:
    name = args.name.strip().strip("/")
    if not name or "/" not in name:
        print("usage: skill new <namespace>/<name>  (e.g. core/digest)", file=sys.stderr)
        return 2
    d = SK / name
    if d.exists():
        print(f"already exists: {d}", file=sys.stderr)
        return 1
    d.mkdir(parents=True, exist_ok=False)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    (d / "SKILL.md").write_text(SKILL_TEMPLATE_MD.format(name=name), encoding="utf-8")
    rs = d / "run.py"
    rs.write_text(RUN_PY_TEMPLATE.format(name=name), encoding="utf-8")
    try:
        rs.chmod(0o700)
    except OSError:
        pass
    mf = dict(MANIFEST_TEMPLATE)
    mf["name"] = name
    (d / "manifest.json").write_text(json.dumps(mf, indent=2) + "\n", encoding="utf-8")
    for p in (d / "SKILL.md", d / "manifest.json"):
        try:
            p.chmod(0o600)
        except OSError:
            pass
    print(f"scaffolded skill: {d}")
    return 0
