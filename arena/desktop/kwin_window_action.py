"""Non-interactive KWin window actions via temporary journal-reporting scripts."""
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


async def kwin_window_action_via_script(action: str, target_id: str, *, x=None, y=None, width=None, height=None, desktop_exec) -> dict[str, object]:
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if not qdbus or not shutil.which("journalctl") or not str(target_id or "").strip():
        return {"ok": False, "backend": "kwin_window_action", "error": "kwin scripting unavailable"}
    probe = await desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /KWin org.kde.KWin.activeOutputName 2>/dev/null', timeout=3)
    if not probe.get("ok") or not (probe.get("stdout") or "").strip():
        return {"ok": False, "backend": "kwin_window_action", "error": "kwin not available"}
    plugin = "arena_window_action_" + uuid.uuid4().hex
    token = "ARENA_KWIN_ACTION_" + uuid.uuid4().hex
    since = int(time.time()) - 2
    reports_dir = BRIDGE_DIR / "reports"
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        reports_dir = Path(tempfile.gettempdir())
    fd, path = tempfile.mkstemp(prefix="arena_kwin_action_", suffix=".js", dir=str(reports_dir))
    spec = {"action": str(action), "target_id": str(target_id), "x": x, "y": y, "width": width, "height": height}
    try:
        js = r'''
function val(o, k, d) { try { var v = o[k]; return (v === undefined || v === null) ? d : v; } catch(e) { return d; } }
function geom(r) { try { return {x:r.x, y:r.y, width:r.width, height:r.height}; } catch(e) { return null; } }
var spec = __SPEC__;
var result = {ok:false, action:spec.action, target_id:spec.target_id, error:null};
var matched = false;
try {
  var list = workspace.windowList ? workspace.windowList() : (workspace.windows || []);
  for (var i = 0; i < list.length; i++) {
    var w = list[i];
    var id = String(val(w, 'windowId', val(w, 'internalId', '')));
    var iid = String(val(w, 'internalId', ''));
    if (id !== spec.target_id && iid !== spec.target_id) continue;
    matched = true;
    result.title = String(val(w, 'caption', ''));
    try {
      if (spec.action === 'minimize') w.minimized = true;
      else if (spec.action === 'restore') {
        try { w.minimized = false; } catch(e) {}
        try { w.fullScreen = false; } catch(e) {}
        try { if (typeof w.setMaximize === 'function') w.setMaximize(false, false); } catch(e) {}
      }
      else if (spec.action === 'maximize') {
        if (typeof w.setMaximize === 'function') w.setMaximize(true, true);
        else result.error = 'maximize_unsupported';
      }
      else if (spec.action === 'unmaximize') {
        if (typeof w.setMaximize === 'function') w.setMaximize(false, false);
        else result.error = 'unmaximize_unsupported';
      }
      else if (spec.action === 'fullscreen') w.fullScreen = true;
      else if (spec.action === 'unfullscreen') w.fullScreen = false;
      else if (spec.action === 'close') {
        if (typeof w.closeWindow === 'function') w.closeWindow();
        else if (typeof workspace.slotWindowClose === 'function') { try { workspace.activeWindow = w; } catch(e) {} workspace.slotWindowClose(); }
        else result.error = 'close_unsupported';
      }
      else if (spec.action === 'move' || spec.action === 'resize' || spec.action === 'move_resize') {
        var g = w.frameGeometry;
        var nx = (spec.x === null || spec.x === undefined) ? g.x : Number(spec.x);
        var ny = (spec.y === null || spec.y === undefined) ? g.y : Number(spec.y);
        var nw = (spec.width === null || spec.width === undefined) ? g.width : Number(spec.width);
        var nh = (spec.height === null || spec.height === undefined) ? g.height : Number(spec.height);
        try { g.x = nx; g.y = ny; g.width = nw; g.height = nh; w.frameGeometry = g; }
        catch(e) { w.frameGeometry = Qt.rect(nx, ny, nw, nh); }
      } else result.error = 'unsupported_action';
      if (!result.error || result.error === 'unsupported_action') result.error = (result.error === 'unsupported_action') ? result.error : null;
      result.ok = result.error === null;
    } catch(e) { result.error = String(e); }
    result.geometry = geom(val(w, 'frameGeometry', null));
    result.minimized = !!val(w, 'minimized', false);
    result.maximized = !!val(w, 'maximized', false);
    result.maximized_horiz = !!val(w, 'maximizedHorizontally', false);
    result.maximized_vert = !!val(w, 'maximizedVertically', false);
    result.full_screen = !!val(w, 'fullScreen', false);
    break;
  }
  if (!matched && result.error === null) result.error = 'window_not_found';
} catch(e) { result.error = String(e); }
print(__TOKEN__ + ' ' + JSON.stringify(result));
'''.replace("__SPEC__", json.dumps(spec)).replace("__TOKEN__", json.dumps(token))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(js)
        load = await desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript {shlex.quote(path)} {shlex.quote(plugin)}', timeout=3)
        if not load.get("ok"):
            return {"ok": False, "backend": "kwin_window_action", "error": "loadScript failed", "detail": load}
        await desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.start', timeout=3)
        for _ in range(20):
            journal = await desktop_exec(f'journalctl --user -b --since @{since} -o cat --no-pager 2>/dev/null | grep {shlex.quote(token)} | tail -1', timeout=3)
            line = (journal.get("stdout") or "").strip()
            if token in line:
                try:
                    return {"backend": "kwin_window_action", **json.loads(line.split(token, 1)[1].strip())}
                except Exception as exc:
                    return {"ok": False, "backend": "kwin_window_action", "error": f"journal parse failed: {exc}"}
            await asyncio.sleep(0.1)
        return {"ok": False, "backend": "kwin_window_action", "error": "script produced no journal output"}
    finally:
        try:
            await desktop_exec(f'{shlex.quote(qdbus)} org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript {shlex.quote(plugin)}', timeout=2)
        except Exception:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass


__all__ = ["kwin_window_action_via_script"]
