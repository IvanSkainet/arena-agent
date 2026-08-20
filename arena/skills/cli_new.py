"""Skill scaffolding command."""
from __future__ import annotations

import re

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
"""Entry point for a scaffolded skill.

Scaffolded as run.py rather than run.sh: Windows is a supported platform and
has no bash on PATH by default, so a shell runner fails out of the box (#126).

Available env: ARENA_AGENT_HOME, SKILL_NAME, SKILL_DIR, SKILL_ARGS (JSON).
"""
from __future__ import annotations

_DEFAULT_NAME_JSON = _SCAFFOLD_NAME_PLACEHOLDER

import json
import os
import sys

# The scaffolder substitutes the literal above: a name is data, not source.
_DEFAULT_NAME = json.loads(_DEFAULT_NAME_JSON)


def main(argv: list[str]) -> int:
    name = os.environ.get("SKILL_NAME") or _DEFAULT_NAME
    print(f"skill {name} running with args: {' '.join(argv)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''

NAME_PLACEHOLDER = "_SCAFFOLD_NAME_PLACEHOLDER"

MANIFEST_TEMPLATE = {
    "name": "",
    "description": "",
    "args": [],
    "timeout": 300,
    "mode": "safe",
}

# A skill name becomes a path fragment, so it needs a path's discipline:
# `../../pwn/x` scaffolded outside the skills tree entirely (#126).
_NAME_PART = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _reject_name(name: str) -> str | None:
    """Return why `name` is unusable as `<namespace>/<name>`, or None."""
    parts = name.split("/")
    if len(parts) != 2:
        return "a skill name is exactly <namespace>/<name>"
    for part in parts:
        if not _NAME_PART.match(part):
            return (
                "each part must start alphanumeric and contain only "
                "letters, digits, dot, dash or underscore"
            )
    return None


def new_skill(args) -> int:
    name = args.name.strip().strip("/")
    problem = _reject_name(name) if name else "a skill name is required"
    if problem:
        print(
            f"usage: skill new <namespace>/<name>  (e.g. core/digest): {problem}",
            file=sys.stderr,
        )
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
    # The name is substituted as a JSON literal, never as source: a name
    # carrying a quote used to close the string and run as code.
    rs.write_text(
        RUN_PY_TEMPLATE.replace(NAME_PLACEHOLDER, json.dumps(json.dumps(name))),
        encoding="utf-8",
    )
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
