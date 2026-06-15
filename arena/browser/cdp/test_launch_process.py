"""Process-level helpers for CDP test-launch diagnostics."""
from __future__ import annotations

import subprocess
import threading
import time

from arena.browser.cdp.test_launch_probe import attach_tabs_if_available, fetch_version_info, is_port_open


def terminate_process(proc) -> None:
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def start_stderr_drain(proc, stderr_lines: list[str]) -> None:
    def _drain():
        try:
            for line in proc.stderr:
                stderr_lines.append(line.decode(errors="replace") if isinstance(line, bytes) else line)
        except Exception:
            pass

    threading.Thread(target=_drain, daemon=True).start()


def run_launch_mode(*, cmd: list[str], env: dict, port: int, mode_name: str, user_data: str) -> dict:
    """Launch Chromium in one mode and probe the debug port while it runs."""
    mode_result = {
        "mode": mode_name,
        "cmd": " ".join(cmd),
        "user_data_dir": user_data,
    }
    proc = None
    stderr_lines: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        start_stderr_drain(proc, stderr_lines)

        port_open = False
        version_info = None
        for attempt in range(16):
            time.sleep(0.5)
            if proc.poll() is not None:
                mode_result["died_after_s"] = (attempt + 1) * 0.5
                mode_result["returncode"] = proc.returncode
                break
            if is_port_open(port):
                port_open = True
                version_info = fetch_version_info(port)
                attach_tabs_if_available(mode_result, port)
                break

        mode_result["port_open"] = port_open
        mode_result["pid"] = proc.pid
        mode_result["still_running"] = proc.poll() is None

        if port_open:
            mode_result["ok"] = True
            if version_info:
                mode_result["version_info"] = version_info
        else:
            mode_result["ok"] = False
            mode_result["stderr_last10"] = [line.strip() for line in stderr_lines[-10:] if line.strip()]
        return mode_result
    except Exception as e:
        mode_result["ok"] = False
        mode_result["error"] = f"{type(e).__name__}: {e}"
        return mode_result
    finally:
        terminate_process(proc)
