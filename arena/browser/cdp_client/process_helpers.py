"""Extracted module from scripts/cdp_browser.py."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403

def _ts() -> str:
    """Return a timestamp string for logging."""
    return time.strftime("%H:%M:%S", time.localtime())

def _drain_stderr(proc, log_path):
    """Drain subprocess stderr to a log file in a background thread."""
    try:
        with open(log_path, "ab") as log_file:
            for line in proc.stderr:
                log_file.write(line if isinstance(line, bytes) else line.encode(errors="replace"))
    except Exception:
        pass

def _kill_port_processes(port: int) -> list:
    """Kill any process listening on the given TCP port. Returns list of killed PIDs."""
    import signal as _signal
    import re
    killed = []
    # Try with ss first
    try:
        result = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            if "pid=" in line:
                pids = re.findall(r'pid=(\d+)', line)
                for pid_str in pids:
                    try:
                        pid = int(pid_str)
                        if pid != os.getpid():
                            os.kill(pid, _signal.SIGTERM)
                            killed.append(pid)
                            logger.info("[CDP] Killed stale process pid %d on port %d", pid, port)
                    except (ProcessLookupError, PermissionError, ValueError):
                        pass
    except FileNotFoundError:
        # ss not found — try lsof
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=3
            )
            for pid_str in result.stdout.strip().split():
                try:
                    pid = int(pid_str)
                    if pid != os.getpid():
                        os.kill(pid, _signal.SIGTERM)
                        killed.append(pid)
                except (ProcessLookupError, PermissionError, ValueError):
                    pass
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    # Give processes time to die
    if killed:
        time.sleep(0.5)
    return killed

def _write_diag_file(diag: dict) -> str:
    """Write diagnostics to a file for post-mortem analysis."""
    try:
        diag_dir = os.path.join(tempfile.gettempdir(), f"cdp-browser-{os.getpid()}")
        os.makedirs(diag_dir, exist_ok=True)
        diag_path = os.path.join(diag_dir, "launch-diag.json")
        with open(diag_path, "w") as f:
            json.dump(diag, f, indent=2, default=str)
        return diag_path
    except Exception:
        return ""
