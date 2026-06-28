
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
      maximized: !!val(w, 'maximized', false),
      maximized_horiz: !!val(w, 'maximizedHorizontally', false),
      maximized_vert: !!val(w, 'maximizedVertically', false),
      full_screen: !!val(w, 'fullScreen', false),
      geometry: geom(val(w, 'frameGeometry', null))
    });
  }
} catch(e) { windows.push({error:String(e)}); }
print("ARENA_KWIN_WINDOWS_a96b3403c68749c392c116298b949e17" + ' ' + JSON.stringify({ok:true, backend:'kwin_journal', count:windows.length, windows:windows}));
