"""Runtime helpers for admin/network management endpoints."""
from __future__ import annotations

import base64
import os
import platform
import re
import secrets
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

CLOUDFLARED_STATE: dict[str, Any] = {"proc": None, "url": "", "log": []}


def sys_funnel_status(*, subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Synchronous helper to check Tailscale funnel status."""
    result: dict[str, Any] = {"ok": True, "tailscale": {}, "funnel": {}}

    try:
        out = subprocess.check_output(["tailscale", "status"], stderr=subprocess.STDOUT, text=True, **subprocess_kwargs())
        result["tailscale"]["status"] = out.strip()[:2000]
        result["tailscale"]["connected"] = bool(out.strip())
    except FileNotFoundError:
        result["tailscale"]["error"] = "tailscale not found"
    except Exception as e:
        result["tailscale"]["error"] = str(e)[:500]

    try:
        out = subprocess.check_output(["tailscale", "funnel", "status"], stderr=subprocess.STDOUT, text=True, **subprocess_kwargs())
        result["funnel"]["status"] = out.strip()[:2000]
        lw = out.lower()
        result["funnel"]["active"] = (
            "funnel on" in lw
            or "proxy http" in lw
            or "serving" in lw
            or "listening" in lw
        )
        m = re.search(r"https://[\w.-]+\.ts\.net[^\s]*", out)
        if m:
            result["funnel"]["url"] = m.group(0)
    except FileNotFoundError:
        result["funnel"]["error"] = "tailscale not found"
    except Exception as e:
        result["funnel"]["error"] = str(e)[:500]

    return result


def token_regenerate(target_path: str = "", *, default_token_file: Path) -> dict[str, Any]:
    """Generate a new token and write it to only this bridge instance's token file."""
    new_tok = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    if target_path:
        target = Path(target_path).expanduser()
    else:
        env = os.environ.get("ARENA_TOKEN_FILE")
        target = Path(env).expanduser() if env else Path(default_token_file)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_tok, encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except Exception:
            pass
        return {
            "ok": True,
            "token": new_tok,
            "written_to": [str(target)],
            "note": (
                "Existing connections still use the OLD token until the bridge restarts. "
                "Use POST /v1/restart, or click Restart Bridge."
            ),
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to write {target}: {e}"}


def _which_windows_or_path(binary: str, candidates: list[str]) -> str | None:
    found = shutil.which(binary)
    if not found and platform.system() == "Windows":
        for candidate in candidates:
            if os.path.isfile(candidate):
                found = candidate
                break
    return found


def tailscale_funnel_action(action: str, port: int) -> dict[str, Any]:
    action = (action or "").lower()
    if action not in ("start", "stop", "status"):
        return {"ok": False, "error": "action must be start|stop|status"}

    ts = _which_windows_or_path(
        "tailscale",
        [
            r"C:\Program Files\Tailscale\tailscale.exe",
            r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        ],
    )
    if not ts:
        return {"ok": False, "error": "tailscale binary not found"}

    if action == "start":
        try:
            r = subprocess.run([ts, "funnel", "--bg", str(port)], capture_output=True, text=True, timeout=15)
            return {"ok": r.returncode == 0, "action": "start", "port": port,
                    "stdout": r.stdout, "stderr": r.stderr, "exit_code": r.returncode}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if action == "stop":
        try:
            r = subprocess.run([ts, "funnel", "--https=443", "off"], capture_output=True, text=True, timeout=15)
            return {"ok": r.returncode == 0, "action": "stop",
                    "stdout": r.stdout, "stderr": r.stderr, "exit_code": r.returncode}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    try:
        r = subprocess.run([ts, "funnel", "status"], capture_output=True, text=True, timeout=10)
        out = r.stdout or ""
        return {"ok": True, "action": "status", "output": out,
                "active": ("funnel on" in out.lower() or "proxy http" in out.lower())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _cloudflared_monitor_thread(proc: subprocess.Popen, port: int) -> None:
    while True:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            break
        line_str = line.strip()
        CLOUDFLARED_STATE["log"].append(line_str)
        if len(CLOUDFLARED_STATE["log"]) > 100:
            CLOUDFLARED_STATE["log"].pop(0)
        match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line_str)
        if match:
            CLOUDFLARED_STATE["url"] = match.group(0)


def cloudflared_funnel_action(
    action: str,
    port: int,
    *,
    root_agent: Path,
    subprocess_kwargs: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    action = (action or "").lower()
    if action not in ("start", "stop", "status"):
        return {"ok": False, "error": "action must be start|stop|status"}

    cf = _which_windows_or_path(
        "cloudflared",
        [
            r"C:\Program Files\cloudflared\cloudflared.exe",
            r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        ],
    )
    if not cf:
        local_cf = Path(root_agent) / ("cloudflared.exe" if platform.system() == "Windows" else "cloudflared")
        if local_cf.exists():
            cf = str(local_cf)

    if action == "start":
        if not cf:
            return {"ok": False, "error": "cloudflared binary not found"}
        if CLOUDFLARED_STATE["proc"] and CLOUDFLARED_STATE["proc"].poll() is None:
            return {"ok": True, "action": "start", "already_running": True, "url": CLOUDFLARED_STATE["url"]}
        CLOUDFLARED_STATE["url"] = ""
        CLOUDFLARED_STATE["log"].clear()
        try:
            CLOUDFLARED_STATE["proc"] = subprocess.Popen(
                [cf, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **subprocess_kwargs(),
            )
            t = threading.Thread(target=_cloudflared_monitor_thread, args=(CLOUDFLARED_STATE["proc"], port), daemon=True)
            t.start()

            for _ in range(20):
                if CLOUDFLARED_STATE["url"] or CLOUDFLARED_STATE["proc"].poll() is not None:
                    break
                time.sleep(0.5)

            active = bool(CLOUDFLARED_STATE["url"])
            if not active:
                proc = CLOUDFLARED_STATE["proc"]
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                CLOUDFLARED_STATE["proc"] = None
                return {"ok": False, "action": "start", "error": "cloudflared timed out generating a tunnel URL", "log": list(CLOUDFLARED_STATE["log"])}
            return {"ok": True, "action": "start", "port": port, "url": CLOUDFLARED_STATE["url"], "log": CLOUDFLARED_STATE["log"]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if action == "stop":
        proc = CLOUDFLARED_STATE["proc"]
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        CLOUDFLARED_STATE["proc"] = None
        CLOUDFLARED_STATE["url"] = ""
        return {"ok": True, "action": "stop"}

    proc = CLOUDFLARED_STATE["proc"]
    running = proc is not None and proc.poll() is None
    installed = cf is not None
    return {
        "ok": True,
        "action": "status",
        "installed": installed,
        "active": running,
        "url": CLOUDFLARED_STATE["url"],
        "log": CLOUDFLARED_STATE["log"] if running else [],
    }
