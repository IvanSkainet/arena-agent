"""Skill runner list/show/path commands."""
from __future__ import annotations

from arena.skills.cli_common import *  # noqa: F401,F403

def list_skills(_args) -> int:
    if not SK.exists():
        print("(no skills installed)")
        return 0
    rows: list[tuple[str, str]] = []
    for skill_md in sorted(SK.rglob("SKILL.md")):
        rel = skill_md.parent.relative_to(SK).as_posix()
        # first non-empty, non-heading line of SKILL.md as one-line description
        desc = ""
        for line in skill_md.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                desc = s[:100]
                break
        rows.append((rel, desc))
    if not rows:
        print("(no skills found)")
        return 0
    width = max(len(r[0]) for r in rows)
    for name, desc in rows:
        print(f"{name.ljust(width)}  {desc}")
    return 0

def show_skill(args) -> int:
    d = find_skill_dir(args.name)
    if not d:
        print(f"skill not found: {args.name}", file=sys.stderr)
        return 2
    md = d / "SKILL.md"
    print(md.read_text(encoding="utf-8"))
    # also list executables
    extras = []
    for fname in ("run.sh", "run.py", "manifest.json"):
        if (d / fname).exists():
            extras.append(fname)
    if extras:
        print(f"\n[files: {', '.join(extras)}]  path: {d}")
    return 0

def path_skill(args) -> int:
    d = find_skill_dir(args.name)
    if not d:
        return 2
    print(d)
    return 0
