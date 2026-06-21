"""Non-interactive KWin focus helper via temporary journal-reporting script."""
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


async def kwin_focus_window_via_script(target_id: str, *, desktop_exec) -> dict[str, object]:
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if not qdbus or not shutil.which("journalctl") or not str(target_id or "").strip():
        return {"ok": False, "backend": "kwin_focus_script", "error": "kwin scripting unavailable"}
    probe = await desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /KWin org.kde.KWin.activeOutputName 2>/dev/null', timeout=3)
    if not probe.get("ok") or not (probe.get("stdout") or "").strip():
        return {"ok": False, "backend": "kwin_focus_script", "error": "kwin not available"}
    plugin = "arena_focus_" + uuid.uuid4().hex
    token = "ARENA_KWIN_FOCUS_" + uuid.uuid4().hex
    since = int(time.time()) - 2
    reports_dir = BRIDGE_DIR / "reports"
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        reports_dir = Path(tempfile.gettempdir())
    fd, path = tempfile.mkstemp(prefix="arena_kwin_focus_", suffix=".js", dir=str(reports_dir))
    try:
        js = r'''
function val(o, k, d) { try { var v = o[k]; return (v === undefined || v === null) ? d : v; } catch(e) { return d; } }
var target = __TARGET__;
var ok = false;
var title = '';
try {
  var list = workspace.windowList ? workspace.windowList() : (workspace.windows || []);
  for (var i = 0; i < list.length; i++) {
    var w = list[i];
    var id = String(val(w, 'windowId', val(w, 'internalId', '')));
    var iid = String(val(w, 'internalId', ''));
    if (id === target || iid === target) {
      try { workspace.activeWindow = w; ok = true; } catch(e) {}
      try { title = String(val(w, 'caption', '')); } catch(e) {}
      break;
    }
  }
} catch(e) { print(__TOKEN__ + ' ' + JSON.stringify({ok:false, error:String(e)})); }
print(__TOKEN__ + ' ' + JSON.stringify({ok:ok, target_id:target, title:title}));
'''.replace("__TARGET__", json.dumps(str(target_id))).replace("__TOKEN__", json.dumps(token))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(js)
        load = await desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript {shlex.quote(path)} {shlex.quote(plugin)}', timeout=3)
        if not load.get("ok"):
            return {"ok": False, "backend": "kwin_focus_script", "error": "loadScript failed", "detail": load}
        await desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.start', timeout=3)
        for _ in range(20):
            journal = await desktop_exec(f'journalctl --user -b --since @{since} -o cat --no-pager 2>/dev/null | grep {shlex.quote(token)} | tail -1', timeout=3)
            line = (journal.get("stdout") or "").strip()
            if token in line:
                try:
                    return {"backend": "kwin_focus_script", **json.loads(line.split(token, 1)[1].strip())}
                except Exception as exc:
                    return {"ok": False, "backend": "kwin_focus_script", "error": f"journal parse failed: {exc}"}
            await asyncio.sleep(0.1)
        return {"ok": False, "backend": "kwin_focus_script", "error": "script produced no journal output"}
    finally:
        try:
            await desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript {shlex.quote(plugin)}', timeout=2)
        except Exception:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass


__all__ = ["kwin_focus_window_via_script"]
