"""Headed persistent browser tools for scenarios that need real GUI.

v4.59.0. Rationale — `browser.shot` (v4.51.x) runs chromium headless
once per call: no user-visible window, no state between calls, no way
to interact with file pickers or JS-heavy pages. That fits screenshots
of static pages but breaks for "log into a service and upload a file"
workflows.

`browser.launch` starts a **visible** chromium (or brave) with a
persistent `--user-data-dir`, records the PID, and returns quickly
after the window shows up. Subsequent `desktop.click` / `desktop.type`
/ `desktop.ocr` steps drive the real GUI. `browser.close` shuts it
down cleanly. `browser.list` returns still-running sessions.

Cross-platform: POSIX first (chromium, brave, google-chrome), then
Windows (msedge, chrome). No Firefox — its --user-data-dir semantics
differ (needs --profile instead) and it doesn't accept an initial URL
on the same line reliably.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content


def _default_state_dir() -> Path:
    override = os.environ.get("ARENA_BROWSER_HEADED_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".arena" / "browser-headed"


_STATE_DIR = _default_state_dir()
_STATE_FILE = _STATE_DIR / "sessions.json"

_LINUX_CANDIDATES = ["chromium", "google-chrome", "google-chrome-stable", "brave", "brave-browser"]
_WIN_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "chrome.exe", "msedge.exe",
]
_MACOS_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]


def _err(msg: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {msg}"}]}


def _find_chrome() -> str | None:
    sysname = platform.system()
    if sysname == "Windows":
        for c in _WIN_CANDIDATES:
            if shutil.which(c):
                return shutil.which(c)
            if os.path.exists(c):
                return c
    elif sysname == "Darwin":
        for c in _MACOS_CANDIDATES:
            if os.path.exists(c):
                return c
    else:
        for c in _LINUX_CANDIDATES:
            p = shutil.which(c)
            if p:
                return p
    return None


def _load_sessions() -> dict[str, Any]:
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sessions(sessions: dict[str, Any]) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(sessions, indent=2))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _prune_dead_sessions() -> dict[str, Any]:
    sessions = _load_sessions()
    alive = {k: v for k, v in sessions.items() if _pid_alive(int(v.get("pid", 0)))}
    if len(alive) != len(sessions):
        _save_sessions(alive)
    return alive


def _launch(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url", "") or "about:blank").strip()
    session = str(args.get("session", "") or "default").strip() or "default"
    width = int(args.get("width", 1366) or 1366)
    height = int(args.get("height", 768) or 768)
    incognito = bool(args.get("incognito", False))
    kiosk = bool(args.get("kiosk", False))

    sessions = _prune_dead_sessions()
    if session in sessions and _pid_alive(int(sessions[session]["pid"])):
        return {
            "ok": False, "error": f"session '{session}' already running (pid={sessions[session]['pid']}). Close it first or pick another session name.",
            "existing": sessions[session],
        }

    chrome = _find_chrome()
    if not chrome:
        return {"ok": False, "error": "no chromium/chrome/brave found on this host"}

    user_data_dir = str(_STATE_DIR / f"profile-{session}")
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome,
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        f"--window-size={width},{height}",
        "--new-window",
    ]
    if incognito:
        cmd.append("--incognito")
    if kiosk:
        cmd.append("--kiosk")
    cmd.append(url)

    # Detach: no capture, new session, ignore SIGHUP.
    try:
        proc = subprocess.Popen(  # nosec B603 -- fully controlled args # nosemgrep: dangerous-subprocess-use-audit
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"failed to spawn chrome: {e}"}

    # Give window ~1.5s to show up so subsequent desktop.click has a target.
    time.sleep(1.5)

    entry = {
        "session": session,
        "pid": proc.pid,
        "url": url,
        "chrome": chrome,
        "user_data_dir": user_data_dir,
        "width": width, "height": height,
        "started_at": time.time(),
    }
    sessions = _load_sessions()
    sessions[session] = entry
    _save_sessions(sessions)
    entry["ok"] = True
    return entry


def _close(args: dict[str, Any]) -> dict[str, Any]:
    session = str(args.get("session", "") or "default").strip() or "default"
    force = bool(args.get("force", False))
    sessions = _prune_dead_sessions()
    if session not in sessions:
        return {"ok": True, "session": session, "note": "no such session (already gone)"}
    pid = int(sessions[session]["pid"])
    if not _pid_alive(pid):
        del sessions[session]
        _save_sessions(sessions)
        return {"ok": True, "session": session, "note": "was already dead"}
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        except OSError as e:
            return {"ok": False, "session": session, "error": str(e)}
    # Wait up to 3s for process to exit
    for _ in range(30):
        if not _pid_alive(pid):
            break
        time.sleep(0.1)
    if _pid_alive(pid):
        return {"ok": False, "session": session, "error": "process did not exit", "pid": pid}
    del sessions[session]
    _save_sessions(sessions)
    return {"ok": True, "session": session, "pid": pid, "force": force}


def _list(_args: dict[str, Any]) -> dict[str, Any]:
    sessions = _prune_dead_sessions()
    return {
        "ok": True,
        "count": len(sessions),
        "sessions": list(sessions.values()),
        "state_file": str(_STATE_FILE),
    }


def handle_browser_headed_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "browser.launch":
        return text_content(json.dumps(_launch(args), ensure_ascii=False))
    if name == "browser.close":
        return text_content(json.dumps(_close(args), ensure_ascii=False))
    if name == "browser.list":
        return text_content(json.dumps(_list(args), ensure_ascii=False))
    return None


BROWSER_HEADED_MCP_TOOLS = [
    {
        "name": "browser.launch",
        "description": (
            "Start a VISIBLE chromium/brave with a persistent user-data-dir. "
            "Unlike browser.shot (headless one-shot), the process stays alive "
            "so subsequent desktop.click/type/key/ocr can drive the real GUI. "
            "`session` names the profile (default 'default') — re-launching "
            "the same session while it's alive is refused. Use browser.close "
            "to shut it down cleanly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "default": "about:blank"},
                "session": {"type": "string", "default": "default"},
                "width": {"type": "integer", "default": 1366},
                "height": {"type": "integer", "default": 768},
                "incognito": {"type": "boolean", "default": False},
                "kiosk": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "browser.close",
        "description": "Close a browser session started via browser.launch. `force=true` sends SIGKILL instead of SIGTERM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session": {"type": "string", "default": "default"},
                "force": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "browser.list",
        "description": "List all still-running browser sessions started via browser.launch.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

__all__ = ["handle_browser_headed_tool", "BROWSER_HEADED_MCP_TOOLS"]
