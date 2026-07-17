"""Project git helper CLI implementation."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
PROJECTS = ROOT / "projects"
CURRENT = PROJECTS / ".current"

def _show_agents_md(proj_dir):
    """Если в проекте есть AGENTS.md / CLAUDE.md / .agents.md — показать первые 40 строк."""
    import pathlib as _pl
    for name in ("AGENTS.md", "agents.md", "CLAUDE.md", ".agents.md"):
        p = _pl.Path(proj_dir) / name
        if p.exists():
            try:
                txt = p.read_text(errors="replace")
                head = "\n".join(txt.splitlines()[:40])
                print()
                print(f"=== {name} ({len(txt)} bytes) ===")
                print(head)
                if len(txt.splitlines()) > 40:
                    print(f"... ({len(txt.splitlines())} lines total)")
            except Exception:
                pass
            return True
    return False

def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

def safe(name):
    s=''.join(c if c.isalnum() or c in '-_.' else '-' for c in name.strip())
    if not s or s.startswith('.'): raise SystemExit('bad project name')
    return s

def project_path(name=None):
    if not name:
        if not CURRENT.exists(): raise SystemExit('no current project; run project-use NAME')
        name=CURRENT.read_text().strip()
    p=PROJECTS/safe(name)
    if not p.exists(): raise SystemExit(f'project not found: {name}')
    return p

def run(cmd, cwd, check=False):
    p=subprocess.run(cmd, shell=True, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # nosec B602 -- project_cli.run is used only from operator-side project CLI; strings are hard-coded git invocations built inside this module.  # nosemgrep: subprocess-shell-true -- legitimate CLI-side helper (see bandit B602 nosec on the same line for the specific rationale)
    if check and p.returncode!=0:
        sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); raise SystemExit(p.returncode)
    return p

def ensure_git_identity(p):
    if run('git config user.email', p).returncode != 0 or not run('git config user.email', p).stdout.strip():
        run('git config user.email "arena-agent@local"', p)
    if run('git config user.name', p).returncode != 0 or not run('git config user.name', p).stdout.strip():
        run('git config user.name "Arena Agent"', p)

def shq(s): return "'"+s.replace("'","'\\''")+"'"
