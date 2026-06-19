"""KWin native window listing helper."""
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
from arena.desktop.exec import _desktop_exec


async def _kwin_windows_via_script() -> dict | None:
    """Best-effort native KDE Plasma/Wayland window listing via KWin script.

    KWin's JS environment in Plasma 6 does not expose QFile, so the temporary
    script prints a single tokenized JSON line to the user journal. The bridge
    reads that line back with journalctl and parses it. If KWin/DBus scripting
    is unavailable, callers fall back to wmctrl/xdotool.
    """
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if not qdbus or not shutil.which("journalctl"):
        return None

    probe = await _desktop_exec(
        f'{shlex.quote(qdbus)} org.kde.KWin /KWin org.kde.KWin.activeOutputName 2>/dev/null',
        timeout=3,
    )
    if not probe.get("ok") or not (probe.get("stdout") or "").strip():
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
"""
        js = js_template.replace("__TOKEN__", json.dumps(token)).replace("__PLUGIN__", json.dumps(plugin))
        with os.fdopen(js_fd, "w", encoding="utf-8") as f:
            f.write(js)

        load = await _desktop_exec(
            f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript {shlex.quote(js_path)} {shlex.quote(plugin)}',
            timeout=3,
        )
        load_id = (load.get("stdout") or "").strip()
        if not load.get("ok"):
            return {"ok": False, "backend": "kwin_journal", "error": "loadScript failed", "detail": load}
        # Plasma may legally return "0" here while still loading the script.
        # Treat the DBus call itself as success and let the journal-output loop
        # decide whether the script actually ran.
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
