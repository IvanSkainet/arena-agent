"""Desktop runtime helpers.

Extracted from unified_bridge.py during v3 modularization.  These helpers are
used by desktop handlers but do not depend on aiohttp.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from arena.constants import BRIDGE_DIR

async def _desktop_exec(cmd: str, timeout: float = 10) -> dict:
    """Run a desktop automation command and return result dict."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": f"Command timed out ({timeout}s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _detect_desktop_env() -> dict:
    """Detect the desktop environment and available tools."""
    import shutil
    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    display = os.environ.get("DISPLAY", "")
    return {
        "session_type": session_type,
        "wayland": bool(wayland_display),
        "x11": bool(display),
        "has_ydotool": shutil.which("ydotool") is not None,
        "has_xdotool": shutil.which("xdotool") is not None,
        "has_spectacle": shutil.which("spectacle") is not None,
        "has_grim": shutil.which("grim") is not None,
        "has_scrot": shutil.which("scrot") is not None,
        "has_wtype": shutil.which("wtype") is not None,
    }


async def _kwin_windows_via_script() -> dict | None:
    """Best-effort native KDE Plasma/Wayland window listing via KWin script.

    KWin's JS environment in Plasma 6 does not expose QFile, so the temporary
    script prints a single tokenized JSON line to the user journal.  The bridge
    reads that line back with journalctl and parses it.  If scripting or journal
    access is unavailable, callers fall back to wmctrl/xdotool.
    """
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if not qdbus:
        return None
    if not shutil.which("journalctl"):
        return None
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if "kde" not in desktop and "plasma" not in desktop and session != "wayland":
        return None

    plugin = "arena_windows_" + uuid.uuid4().hex
    token = "ARENA_KWIN_WINDOWS_" + uuid.uuid4().hex
    since = int(time.time()) - 2
    reports_dir = BRIDGE_DIR / "reports"
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        reports_dir = Path(tempfile.gettempdir())
    js_fd, js_path = tempfile.mkstemp(prefix="arena_kwin_windows_", suffix=".js", dir=str(reports_dir))
    try:
        js_template = r"""
function val(o, k, d) { try { var v = o[k]; return (v === undefined || v === null) ? d : v; } catch(e) { return d; } }
function geom(r) { try { return {x:r.x, y:r.y, width:r.width, height:r.height}; } catch(e) { return null; } }
var windows = [];
try {
  var list = [];
  if (workspace.windowList) list = workspace.windowList();
  else if (workspace.windows) list = workspace.windows;
  for (var i = 0; i < list.length; i++) {
    var w = list[i];
    windows.push({
      id: String(val(w, 'windowId', val(w, 'internalId', ''))),
      internal_id: String(val(w, 'internalId', '')),
      title: String(val(w, 'caption', '')),
      pid: val(w, 'pid', null),
      resource_class: String(val(w, 'resourceClass', '')),
      resource_name: String(val(w, 'resourceName', '')),
      desktop_file: String(val(w, 'desktopFileName', '')),
      active: !!val(w, 'active', false),
      minimized: !!val(w, 'minimized', false),
      full_screen: !!val(w, 'fullScreen', false),
      geometry: geom(val(w, 'frameGeometry', null))
    });
  }
} catch(e) { windows.push({error:String(e)}); }
print(__TOKEN__ + ' ' + JSON.stringify({ok:true, backend:'kwin_journal', count:windows.length, windows:windows}));
callDBus('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting', 'unloadScript', __PLUGIN__);
"""
        js = js_template.replace("__TOKEN__", json.dumps(token)).replace("__PLUGIN__", json.dumps(plugin))
        with os.fdopen(js_fd, "w", encoding="utf-8") as f:
            f.write(js)

        load = await _desktop_exec(
            f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript {shlex.quote(js_path)} {shlex.quote(plugin)}',
            timeout=3,
        )
        load_id = (load.get("stdout") or "").strip()
        if not load.get("ok") or not load_id or load_id == "0":
            return {"ok": False, "backend": "kwin_journal", "error": "loadScript failed", "detail": load}
        await _desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.start', timeout=3)

        for _ in range(20):
            journal = await _desktop_exec(
                f'journalctl --user -b --since @{since} -o cat --no-pager 2>/dev/null | grep {shlex.quote(token)} | tail -1',
                timeout=3,
            )
            line = (journal.get("stdout") or "").strip()
            if token in line:
                try:
                    payload = line.split(token, 1)[1].strip()
                    data = json.loads(payload)
                    if isinstance(data, dict) and data.get("ok"):
                        return data
                except Exception as e:
                    return {"ok": False, "backend": "kwin_journal", "error": f"journal parse failed: {e}", "line": line[:500]}
            await asyncio.sleep(0.1)
        return {"ok": False, "backend": "kwin_journal", "error": "script produced no journal output"}
    finally:
        try:
            await _desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript {shlex.quote(plugin)}', timeout=2)
        except Exception:
            pass
        try:
            os.unlink(js_path)
        except OSError:
            pass


async def _get_active_window() -> dict | None:
    """Get currently active (focused) window info. Used by input guard.

    Tries multiple backends in order of reliability:
    1. KWin DBus (KDE Plasma Wayland — most reliable)
    2. xdotool (X11 / XWayland)
    3. kdotool (KDE Wayland fallback)
    4. wmctrl (generic fallback)
    Returns dict with id, title, pid, class or None.
    """
    display_env = f'DISPLAY={os.environ.get("DISPLAY", ":0")}'

    # Strategy 0: KWin DBus (KDE Plasma Wayland — native, most reliable)
    # Uses org.kde.KWin to get active window caption and ID
    if shutil.which("dbus-send") or shutil.which("qdbus") or shutil.which("qdbus6"):
        try:
            # Try qdbus6 first (KDE Plasma 6)
            qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
            if qdbus:
                # Get active window caption
                result = await _desktop_exec(
                    f'{qdbus} org.kde.KWin /KWin org.kde.KWin.getActiveOutputName 2>/dev/null',
                    timeout=2)
                # Get active window info via KWin scripting
                result = await _desktop_exec(
                    f'{qdbus} org.kde.KWin /KWin supportInformation 2>/dev/null | '
                    f'grep -A2 "Active window"',
                    timeout=3)
                # Simpler approach: get active window via kscreen/kwin
                result = await _desktop_exec(
                    f'dbus-send --session --dest=org.kde.KWin --type=method_call '
                    f'--print-reply /KWin org.kde.KWin.getActiveWindowId 2>/dev/null',
                    timeout=3)
                if result["ok"] and result["stdout"].strip():
                    # Parse int32 from dbus reply
                    import re as _re
                    match = _re.search(r'int32\s+(\d+)|int64\s+(\d+)', result["stdout"])
                    if match:
                        wid = match.group(1) or match.group(2)
                        if wid and wid != "0":
                            # Get window caption
                            caption_r = await _desktop_exec(
                                f'dbus-send --session --dest=org.kde.KWin --type=method_call '
                                f'--print-reply /KWin org.kde.KWin.getWindowCaption int32:{wid} 2>/dev/null',
                                timeout=2)
                            title = ""
                            if caption_r["ok"] and caption_r["stdout"].strip():
                                # Parse string from dbus reply: string "caption"
                                cap_match = _re.search(r'string\s+"(.+)"', caption_r["stdout"])
                                if cap_match:
                                    title = cap_match.group(1)
                            return {
                                "id": wid,
                                "title": title,
                                "backend": "kwin_dbus",
                            }
        except Exception:
            pass  # Fall through to other strategies

    # Strategy 1: xdotool getactivewindow (X11 / XWayland)
    if shutil.which("xdotool"):
        result = await _desktop_exec(
            f'{display_env} xdotool getactivewindow 2>/dev/null', timeout=3)
        if result["ok"] and result["stdout"].strip():
            wid = result["stdout"].strip().split("\n")[0]
            name_r = await _desktop_exec(
                f'{display_env} xdotool getwindowname {wid} 2>/dev/null', timeout=2)
            pid_r = await _desktop_exec(
                f'{display_env} xdotool getwindowpid {wid} 2>/dev/null', timeout=2)
            cls_r = await _desktop_exec(
                f'{display_env} xdotool getwindowclassname {wid} 2>/dev/null || '
                f'xprop -id {wid} WM_CLASS 2>/dev/null | cut -d\\" -f2', timeout=2)
            geom_r = await _desktop_exec(
                f'{display_env} xdotool getwindowgeometry {wid} 2>/dev/null', timeout=2)
            return {
                "id": wid,
                "title": name_r.get("stdout", "").strip() if name_r["ok"] else "",
                "pid": pid_r.get("stdout", "").strip() if pid_r["ok"] else None,
                "class": cls_r.get("stdout", "").strip() if cls_r["ok"] else "",
                "geometry": geom_r.get("stdout", "").strip() if geom_r["ok"] else "",
                "backend": "xdotool",
            }

    # Strategy 2: kdotool (KDE Plasma Wayland)
    if shutil.which("kdotool"):
        result = await _desktop_exec(
            'kdotool search --active 2>/dev/null || '
            'kdotool search --onlyvisible --active 2>/dev/null', timeout=3)
        if result["ok"] and result["stdout"].strip():
            wid = result["stdout"].strip().split("\n")[0]
            return {
                "id": wid,
                "title": "",  # kdotool doesn't easily give title
                "backend": "kdotool",
            }

    # Strategy 3: wmctrl active window (reads * marker)
    if shutil.which("wmctrl"):
        result = await _desktop_exec(
            f'{display_env} wmctrl -l -p 2>/dev/null', timeout=3)
        if result["ok"]:
            for line in result["stdout"].strip().split("\n"):
                if "*" in line:
                    parts = line.split(None, 5)
                    if len(parts) >= 5:
                        return {
                            "id": parts[0],
                            "desktop": parts[1],
                            "pid": parts[2],
                            "host": parts[3],
                            "title": parts[4] if len(parts) == 5 else " ".join(parts[4:]),
                            "active": True,
                            "backend": "wmctrl",
                        }

    return None
