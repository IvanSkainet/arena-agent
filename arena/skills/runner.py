"""Skill execution helpers."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

def run_skill(name: str, args: list[str], *, skills_dir: Path, root_agent: Path, bin_dir: Path, subprocess_kwargs_fn, env_extra: dict | None = None) -> dict:
    """Execute a skill via agentctl or directly.

    Supports three skill types:
    1. Executable skills: have run.sh or run.py — executed as subprocess
    2. Prompt-only skills: have SKILL.md but no runner — return SKILL.md content
    3. Fallback: try agentctl skill run
    """
    # Try direct skill runner first (faster, supports JSON input via env)
    skill_dir = skills_dir / name
    if not skill_dir.exists() and skills_dir.exists():
        # Try flat name under skills/ (e.g. "browseract" -> skills/browseract/)
        for d in skills_dir.iterdir():
            if d.is_dir() and d.name == name:
                skill_dir = d
                break
        else:
            # Recursive search: "health" could be at skills/core/health/
            # Also find prompt-only skills (SKILL.md without runner)
            for d in skills_dir.rglob(name):
                if d.is_dir():
                    # Check for any valid runner
                    valid = False
                    for cand in ["run.sh", "run.py", "SKILL.md", f"{d.name}.py", f"{d.name}.sh", "main.py", "app.py", "start.sh", "index.js", f"{d.name}"]:
                        if (d / cand).exists():
                            valid = True
                            break
                    if valid:
                        skill_dir = d
                        break

    runner_sh = skill_dir / "run.sh"
    runner_py = skill_dir / "run.py"
    skill_md = skill_dir / "SKILL.md"

    # Fallback to common generic entrypoints for third_party skills
    if not runner_sh.exists() and not runner_py.exists() and skill_dir.exists():
        for candidate in [f"{skill_dir.name}.py", f"{skill_dir.name}.sh", "main.py", "app.py", "start.sh", "index.js", f"{skill_dir.name}"]:
            cp = skill_dir / candidate
            if cp.exists() and cp.is_file():
                if candidate.endswith(".py"): runner_py = cp
                elif candidate.endswith(".js"): runner_sh = cp # Will handle JS in exec
                else: runner_sh = cp
                break

    # --- Executable skills (run.sh / run.py) ---
    if skill_dir.exists() and (runner_sh.exists() or runner_py.exists()):
        # Direct execution — faster, passes input via env vars
        env = os.environ.copy()
        env["ARENA_AGENT_HOME"] = str(root_agent)
        env["SKILL_NAME"] = name
        env["SKILL_DIR"] = str(skill_dir)
        env["SKILL_ARGS"] = json.dumps(args)
        # Filter dangerous env vars from user-supplied extras
        if env_extra:
            _SKILL_BLOCKED_ENV = {"ARENA_TOKEN", "TOKEN", "SECRET", "PASSWORD", "KEY",
                                   "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH",
                                   "PYTHONSTARTUP"}
            for k, v in env_extra.items():
                if not any(b in k.upper() for b in _SKILL_BLOCKED_ENV):
                    env[k] = str(v) if not isinstance(v, str) else v

        # On Windows, prefer run.py over run.sh (bash may not be available)
        if sys.platform == "win32" and runner_py.exists():
            py = sys.executable or "python3"
            cmd = [py, str(runner_py)] + list(args)
        elif runner_sh.exists():
            if runner_sh.suffix == ".js":
                cmd = ["node", str(runner_sh)] + list(args)
            elif runner_sh.suffix == ".py":
                cmd = ["python3", str(runner_sh)] + list(args)
            elif runner_sh.name == skill_dir.name and not "." in runner_sh.name:
                with open(runner_sh, 'rb') as f:
                    shebang = f.read(50)
                    if b"python" in shebang:
                        cmd = ["python3", str(runner_sh)] + list(args)
                    else:
                        bash_path = shutil.which("bash") or "bash"
                        cmd = [bash_path, str(runner_sh)] + list(args)
            else:
                # Use bash to execute .sh files (git may not preserve +x bit)
                bash_path = shutil.which("bash")
                if not bash_path:
                    return {"ok": False, "exit_code": -2, "stdout": "",
                            "stderr": "bash not available — .sh skills require WSL or Git Bash on Windows"}
                cmd = [bash_path, str(runner_sh)] + list(args)
        else:
            py = sys.executable or "python3"
            cmd = [py, str(runner_py)] + list(args)

        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                               env=env, **subprocess_kwargs_fn())
            return {"ok": p.returncode == 0, "exit_code": p.returncode,
                    "stdout": p.stdout[-15000:], "stderr": p.stderr[-3000:]}
        except subprocess.TimeoutExpired:
            return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "timeout"}
        except Exception as e:
            return {"ok": False, "exit_code": -2, "stdout": "", "stderr": str(e)}

    # --- Prompt-only skills (SKILL.md without runner) ---
    # These are instruction/prompt skills (e.g., SuperPowers) — return SKILL.md content
    if skill_dir.exists() and skill_md.exists() and not runner_sh.exists() and not runner_py.exists():
        try:
            content = skill_md.read_text(encoding="utf-8")
            return {
                "ok": True,
                "exit_code": 0,
                "output": content,
                "skill_type": "prompt",
                "skill_name": name,
                "skill_dir": str(skill_dir),
                "stdout": content[:500] + ("..." if len(content) > 500 else ""),
                "stderr": "",
            }
        except Exception as e:
            return {"ok": False, "exit_code": -2, "stdout": "", "stderr": f"Failed to read SKILL.md: {e}"}

    # Fallback: agentctl skill run
    cmd_args = [os.path.join(bin_dir, "agentctl"), "skill", "run", name] + list(args)
    try:
        p = subprocess.run(cmd_args, capture_output=True, text=True, timeout=300, **subprocess_kwargs_fn())
        return {"ok": p.returncode == 0, "exit_code": p.returncode,
                "stdout": p.stdout[-15000:], "stderr": p.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "exit_code": -2, "stdout": "", "stderr": str(e)}
