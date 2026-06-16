"""Project AGENTS.md helper command."""
from __future__ import annotations

from arena.project_cli.common import *  # noqa: F401,F403

def agents_md_command(args):
    """CLI: project_git.py agents [init|show] — управление AGENTS.md в текущем проекте."""
    import os as _os, pathlib as _pl, shutil as _sh
    state = _pl.Path.home() / "arena-bridge" / "current_project"
    cur = None
    if state.exists(): cur = state.read_text().strip()
    if not cur:
        # пробуем найти через arena-bridge в текущем
        cur = _os.environ.get("ARENA_CURRENT_PROJECT", "")
    if not cur:
        # последний из projects/
        proj_root = _pl.Path.home() / "arena-bridge" / "projects"
        if proj_root.exists():
            dirs = sorted([d for d in proj_root.iterdir() if d.is_dir()],
                          key=lambda p: p.stat().st_mtime, reverse=True)
            if dirs: cur = str(dirs[0])
    if not cur:
        print("No current project. Use `agentctl proj use NAME` first.")
        return 1
    proj_dir = _pl.Path(cur)
    if not proj_dir.is_absolute():
        proj_dir = _pl.Path.home() / "arena-bridge" / "projects" / proj_dir
    sub = args[0] if args else "show"
    target = proj_dir / "AGENTS.md"
    if sub == "init":
        tmpl = _pl.Path.home() / "arena-bridge" / "docs" / "AGENTS.md.template"
        if not tmpl.exists():
            print("template missing:", tmpl); return 1
        if target.exists():
            print("already exists:", target); return 1
        text = tmpl.read_text().replace("{name}", proj_dir.name)
        target.write_text(text)
        print("created:", target)
        return 0
    # show
    if not target.exists():
        print(f"no AGENTS.md at {target}\nrun: agentctl proj agents init")
        return 1
    print(target.read_text())
    return 0
