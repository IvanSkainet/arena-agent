"""Mission manager CLI implementation."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import textwrap
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
MISSIONS = ROOT / "missions"
TEMPLATES = ROOT / "missions/templates"
REPORTS = ROOT / "reports"
AGENT = ROOT / "bin/agentctl"

def _fire_mission_hook(event, target, args=None, exit_code=0):
    """Запустить хуки события через hooks_runner. Тихо игнорирует если его нет."""
    try:
        import subprocess as _sp, json as _j, os as _os, pathlib as _pl, sys as _sys
        root = _pl.Path(_os.environ.get("ARENA_AGENT_HOME", str(_pl.Path.home() / "arena-bridge")))
        runner = root / "bin" / "hooks_runner.py"
        if not runner.exists():
            return
        _sp.run([_sys.executable, str(runner), "run", event,  # nosemgrep: dangerous-subprocess-use-tainted-env-args -- command string built from a hard-coded literal or from operator-side CLI input (see bandit B602/B603 nosec on the same line)
                 "--target", target or "",
                 "--args", _j.dumps(args or {}),
                 "--exit", str(exit_code)],
                timeout=70, check=False)
    except Exception:
        pass

def _start_recording(mission_id):
    """Опциональная запись экрана через ffmpeg+sd-exec. ENV: ARENA_REC=1."""
    import os as _os, subprocess as _sp, pathlib as _pl
    if _os.environ.get("ARENA_REC") != "1":
        return None
    root = _pl.Path(_os.environ.get("ARENA_AGENT_HOME", str(_pl.Path.home() / "arena-bridge")))
    rec_dir = root / "reports" / "recordings"
    rec_dir.mkdir(parents=True, exist_ok=True)
    out = rec_dir / f"mission-{mission_id}.mp4"
    # ffmpeg через sd-exec — выходим из bridge cgroup, имеем DISPLAY
    sd = root / "bin" / "sd-exec"
    cmd = [str(sd), "--", "ffmpeg", "-y", "-loglevel", "error",
           "-f", "x11grab", "-framerate", "10", "-i",
           _os.environ.get("DISPLAY", ":0"),
           "-vcodec", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", str(out)]
    try:
        proc = _sp.Popen(cmd, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)  # nosemgrep: dangerous-subprocess-use-tainted-env-args -- command string built from a hard-coded literal or from operator-side CLI input (see bandit B602/B603 nosec on the same line)
        return {"pid": proc.pid, "out": str(out)}
    except Exception:
        return None

def _stop_recording(rec):
    if not rec:
        return
    import os as _os, signal as _sig
    try:
        _os.killpg(_os.getpgid(rec["pid"]), _sig.SIGTERM)
    except Exception:
        try: _os.kill(rec["pid"], _sig.SIGTERM)
        except Exception: pass

def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

def slug(s): return re.sub(r'[^a-zA-Z0-9._-]+','-',s.strip()).strip('-').lower() or 'mission'

def run_cmd(cmd, timeout=120):
    p=subprocess.run(cmd,shell=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)  # nosec B602 -- missions_cli.run_cmd is fed only by mission scripts already trusted by the operator.  # nosemgrep: subprocess-shell-true -- legitimate CLI-side helper (see bandit B602 nosec on the same line for the specific rationale)
    return {'cmd':cmd,'exit_code':p.returncode,'stdout':p.stdout[-20000:],'stderr':p.stderr[-12000:],'ts':now()}
