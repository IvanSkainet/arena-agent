#!/usr/bin/env python3
"""agents_md — управление AGENTS.md в проектах Arena Agent.

Usage:
  agents_md show [PROJECT]   — показать AGENTS.md проекта (по умолчанию текущий)
  agents_md init [PROJECT]   — создать AGENTS.md из шаблона
  agents_md ls               — список AGENTS.md по всем проектам
"""
from __future__ import annotations
import sys, pathlib

ROOT = pathlib.Path.home() / "arena-bridge"
PROJ = ROOT / "projects"
TMPL = ROOT / "docs" / "AGENTS.md.template"
STATE = pathlib.Path.home() / ".arena-bridge" / "current_project"


def current_project():
    if STATE.exists():
        name = STATE.read_text().strip()
        if name:
            p = PROJ / name
            if p.is_dir():
                return p
    if PROJ.exists():
        ds = sorted([d for d in PROJ.iterdir() if d.is_dir()],
                    key=lambda x: x.stat().st_mtime, reverse=True)
        if ds:
            return ds[0]
    return None


def resolve(arg):
    if not arg:
        return current_project()
    p = PROJ / arg
    return p if p.is_dir() else None


def cmd_show(name):
    d = resolve(name)
    if not d:
        print("no project"); return 1
    for nm in ("AGENTS.md", "agents.md", "CLAUDE.md", ".agents.md"):
        f = d / nm
        if f.exists():
            print("=== " + d.name + "/" + nm + " ===")
            print(f.read_text())
            return 0
    print("no AGENTS.md in " + str(d))
    print("run: agents_md init " + d.name)
    return 1


def cmd_init(name):
    d = resolve(name)
    if not d:
        print("no project"); return 1
    if not TMPL.exists():
        print("template missing: " + str(TMPL)); return 2
    target = d / "AGENTS.md"
    if target.exists():
        print("already exists: " + str(target)); return 0
    text = TMPL.read_text().replace("{name}", d.name)
    target.write_text(text)
    print("created: " + str(target))
    return 0


def cmd_ls():
    if not PROJ.exists():
        print("no projects dir"); return 1
    for d in sorted(PROJ.iterdir()):
        if not d.is_dir():
            continue
        marks = []
        for nm in ("AGENTS.md", "CLAUDE.md", "agents.md"):
            if (d / nm).exists():
                marks.append(nm)
        status = ("OK: " + ", ".join(marks)) if marks else "(none)"
        print("{:30s}  {}".format(d.name, status))
    return 0


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__); return 0
    cmd = args[0]
    arg = args[1] if len(args) > 1 else None
    if cmd == "show":
        return cmd_show(arg)
    if cmd == "init":
        return cmd_init(arg)
    if cmd == "ls":
        return cmd_ls()
    print("unknown: " + cmd); return 2


if __name__ == "__main__":
    sys.exit(main())
