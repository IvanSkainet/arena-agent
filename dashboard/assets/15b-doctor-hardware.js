// Doctor tab: cross-platform hardware inventory renderer (v3.86.3).
//
// Talks to GET /v1/hardware, which returns a rich JSON blob that
// arena/system/hwinfo_collect.py has been building for a while.
// Historically the Dashboard never rendered any of it -- the data
// was only visible via curl. This module fixes that and gives the
// AI agent a copyable full-JSON block for deeper diagnostics.
//
// Renders one card per subsystem. Order is intentionally
// "most-glanceable first": CPU + memory + GPU + disks up top so an
// operator's first look tells them "is this box happy right now".
// BIOS / motherboard / package managers / browsers land lower
// because they change once per install, not per-second.
//
// Cross-platform note: the backend fills in what it can on each OS
// (GNU/Linux, macOS, Windows). We NEVER render "undefined" or
// "null" -- missing values become "—" so the layout stays sane on
// hosts that don't expose e.g. BIOS release date.

function _hwEl(id) { return document.getElementById(id); }

function _hwEsc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _hwFmtNumber(n, digits) {
  if (n == null || Number.isNaN(n)) return "—";
  if (typeof digits !== "number") digits = 0;
  return Number(n).toFixed(digits);
}

function _hwFmtGB(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return _hwFmtNumber(n, 1) + " GB";
}

function _hwFmtSeconds(sec) {
  if (sec == null || Number.isNaN(sec)) return "—";
  sec = Math.round(sec);
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return d + "d " + h + "h " + m + "m";
  if (h > 0) return h + "h " + m + "m";
  return m + "m";
}

function _hwCard(title, rows) {
  const body = rows.map(([k, v]) => {
    if (v === null || v === undefined || v === "" || v === "unknown") {
      v = "—";
    }
    return '<tr>'
      + '<td style="padding:2px 8px 2px 0;color:#666;vertical-align:top;white-space:nowrap;font-size:12px">'
      + _hwEsc(k) + '</td>'
      + '<td style="padding:2px 0;font-size:12px;word-break:break-word">' + v + '</td>'
      + '</tr>';
  }).join("");
  return '<div class="hw-card" style="border:1px solid #eee;border-radius:6px;padding:10px;background:#fff">'
    + '<div style="font-weight:600;margin-bottom:6px;font-size:13px">' + _hwEsc(title) + '</div>'
    + '<table style="width:100%;border-collapse:collapse">' + body + '</table>'
    + '</div>';
}

function _hwRenderCPU(cpu) {
  if (!cpu) return "";
  return _hwCard("CPU", [
    ["Model",    _hwEsc(cpu.name)],
    ["Cores",    (cpu.cores || "?") + " physical · " + (cpu.threads || "?") + " logical"],
    ["Current",  _hwFmtNumber(cpu.current_ghz, 2) + " GHz"],
    ["Max",      _hwFmtNumber(cpu.max_ghz, 2) + " GHz"],
    ["Load avg", cpu.load_avg
        ? cpu.load_avg.map(x => _hwFmtNumber(x, 2)).join(" · ")
        : "—"],
    ["Vendor",   _hwEsc(cpu.manufacturer)],
    ["Arch",     _hwEsc(cpu.raw && cpu.raw.machine)],
  ]);
}

function _hwRenderMemory(mem) {
  if (!mem) return "";
  const usedPct = (mem.total_gb && mem.used_gb)
    ? Math.round((mem.used_gb / mem.total_gb) * 100) + "%"
    : "—";
  const bar = (mem.total_gb && mem.used_gb) ? '<div style="height:6px;background:#eee;border-radius:3px;overflow:hidden;margin-top:4px"><div style="height:6px;background:#3a7bd5;width:' + Math.min(100, Math.round((mem.used_gb / mem.total_gb) * 100)) + '%"></div></div>' : '';
  return _hwCard("Memory", [
    ["Total",     _hwFmtGB(mem.total_gb)],
    ["Used",      _hwFmtGB(mem.used_gb) + " (" + usedPct + ")" + bar],
    ["Available", _hwFmtGB(mem.available_gb)],
    ["Swap",      _hwFmtGB(mem.swap_total_gb) + " total · "
                  + _hwFmtGB(mem.swap_free_gb) + " free"],
    ["Modules",   (mem.modules && mem.modules.length)
                  ? mem.modules.length + " installed"
                  : "—"],
  ]);
}

function _hwRenderGPU(gpu, gpus) {
  const list = (gpus && gpus.length) ? gpus : (gpu ? [gpu] : []);
  if (!list.length) return "";
  const rows = [];
  list.forEach((g, i) => {
    const prefix = list.length > 1 ? ("GPU " + i + " ") : "";
    rows.push([prefix + "Model", _hwEsc(g.name)]);
    if (g.driver) rows.push([prefix + "Driver", _hwEsc(g.driver)]);
    if (g.vram_total_mb) {
      rows.push([prefix + "VRAM",
        _hwFmtNumber(g.vram_total_mb, 0) + " MB total"
        + (g.vram_used_mb != null ? " · " + _hwFmtNumber(g.vram_used_mb, 0) + " MB used" : "")]);
    }
    if (g.temperature_c != null) {
      rows.push([prefix + "Temp", g.temperature_c + " °C"]);
    }
    if (g.utilization_pct != null) {
      rows.push([prefix + "Util", g.utilization_pct + "%"]);
    }
  });
  return _hwCard("GPU", rows);
}

function _hwRenderDisks(disks) {
  if (!disks || !disks.length) return "";
  const rows = disks.slice(0, 10).map((d) => {
    const label = _hwEsc(d.mount || d.device || "?");
    const used = (d.used_gb != null && d.total_gb)
      ? _hwFmtGB(d.used_gb) + " / " + _hwFmtGB(d.total_gb) + " · " + Math.round(d.used_pct || 0) + "%"
      : "—";
    const bar = (d.used_pct != null)
      ? '<div style="height:4px;background:#eee;border-radius:2px;overflow:hidden;margin-top:2px"><div style="height:4px;background:' + (d.used_pct > 90 ? "#c92a2a" : d.used_pct > 75 ? "#c9740c" : "#2b8a3e") + ';width:' + Math.min(100, d.used_pct) + '%"></div></div>'
      : '';
    return [label, used + bar];
  });
  return _hwCard("Storage", rows);
}

function _hwRenderOS(os) {
  if (!os) return "";
  const distro = os.distro || {};
  const platformDisplay = os.system === "Linux" ? "GNU/Linux"
    : os.system === "Darwin" ? "macOS" : os.system || "?";
  return _hwCard("Operating System", [
    ["Platform",     _hwEsc(platformDisplay)],
    ["Distribution", _hwEsc(distro.pretty || distro.name || "—")],
    ["Kernel",       _hwEsc(os.release)],
    ["Arch",         _hwEsc(os.machine)],
    ["Uptime",       _hwFmtSeconds(os.uptime_seconds)],
    ["Python",       _hwEsc(os.python_implementation + " " + os.python_version)],
  ]);
}

function _hwRenderMotherboard(mb, bios) {
  if (!mb && !bios) return "";
  return _hwCard("Motherboard & BIOS", [
    ["Manufacturer", _hwEsc(mb && mb.manufacturer)],
    ["Model",        _hwEsc(mb && mb.product)],
    ["Version",      _hwEsc(mb && mb.version)],
    ["BIOS vendor",  _hwEsc(bios && bios.manufacturer)],
    ["BIOS version", _hwEsc(bios && bios.version)],
    ["BIOS date",    _hwEsc(bios && bios.release_date)],
  ]);
}

function _hwRenderNetwork(net) {
  if (!net) return "";
  const rows = [];
  const ifaces = net.interfaces || net.adapters || (Array.isArray(net) ? net : []);
  if (Array.isArray(ifaces) && ifaces.length) {
    ifaces.slice(0, 10).forEach((n) => {
      const addr = n.address || n.ipv4 || n.ip || "—";
      const speed = n.speed_mbps ? (" · " + n.speed_mbps + " Mbps") : "";
      const status = n.status || n.state || "";
      rows.push([_hwEsc(n.name || n.interface || "?"),
                 _hwEsc(addr) + speed + (status ? (" · " + _hwEsc(status)) : "")]);
    });
  } else if (typeof net === "object") {
    Object.entries(net).slice(0, 6).forEach(([k, v]) =>
      rows.push([_hwEsc(k), _hwEsc(typeof v === "object" ? JSON.stringify(v) : v)]));
  }
  return rows.length ? _hwCard("Network", rows) : "";
}

function _hwRenderThermal(thermal) {
  if (!thermal) return "";
  const rows = [];
  if (Array.isArray(thermal)) {
    thermal.slice(0, 10).forEach((t) => {
      rows.push([_hwEsc(t.name || t.label || "?"),
                 (t.temp_c != null ? t.temp_c + " °C" : "—")]);
    });
  } else if (typeof thermal === "object") {
    Object.entries(thermal).forEach(([k, v]) => {
      rows.push([_hwEsc(k),
        (typeof v === "number" ? v + " °C" : _hwEsc(v))]);
    });
  }
  return rows.length ? _hwCard("Thermal sensors", rows) : "";
}

function _hwRenderExtra(hw) {
  // Package managers, browsers, runtimes -- lower priority, one
  // compact card each so operators see they exist.
  const extras = [];
  if (hw.package_managers && Object.keys(hw.package_managers).length) {
    const rows = Object.entries(hw.package_managers).map(([k, v]) =>
      [_hwEsc(k), _hwEsc(typeof v === "object" ? (v.version || "yes") : v)]);
    extras.push(_hwCard("Package managers", rows));
  }
  if (hw.runtimes && Object.keys(hw.runtimes).length) {
    const rows = Object.entries(hw.runtimes).map(([k, v]) =>
      [_hwEsc(k), _hwEsc(typeof v === "object" ? (v.version || "yes") : v)]);
    extras.push(_hwCard("Runtimes", rows));
  }
  if (hw.browsers && Object.keys(hw.browsers).length) {
    const rows = Object.entries(hw.browsers).map(([k, v]) =>
      [_hwEsc(k), _hwEsc(typeof v === "object" ? (v.version || "yes") : v)]);
    extras.push(_hwCard("Browsers", rows));
  }
  return extras.join("");
}

async function doctorLoadHardware() {
  const target = _hwEl("hwCards");
  const rawEl = _hwEl("hwRawJson");
  const timeEl = _hwEl("hwGeneratedAt");
  if (target) target.innerHTML = '<div style="color:#999;font-size:12px">Loading hardware inventory…</div>';
  try {
    const r = await api("/v1/hardware");
    if (!r || r.ok !== true) {
      target.innerHTML = '<div style="color:#c92a2a">Hardware fetch failed: ' + _hwEsc((r && r.error) || "unknown") + '</div>';
      return;
    }
    const hw = r.hardware || {};
    if (timeEl && hw.generated_at) {
      timeEl.textContent = "collected " + new Date(hw.generated_at).toLocaleString();
    }
    const cards = [
      _hwRenderOS(hw.os),
      _hwRenderCPU(hw.cpu),
      _hwRenderMemory(hw.memory),
      _hwRenderGPU(hw.gpu, hw.gpus),
      _hwRenderDisks(hw.disks),
      _hwRenderThermal(hw.thermal),
      _hwRenderMotherboard(hw.motherboard, hw.bios),
      _hwRenderNetwork(hw.network),
      _hwRenderExtra(hw),
    ].filter(Boolean);
    if (!cards.length) {
      target.innerHTML = '<div style="color:#a80">Backend returned empty hardware payload.</div>';
    } else {
      target.innerHTML = cards.join("");
    }
    if (rawEl) rawEl.textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    target.innerHTML = '<div style="color:#c92a2a">Hardware fetch failed: ' + _hwEsc(e && e.message || e) + '</div>';
  }
}

// Auto-run once when the Doctor tab first becomes visible so the
// operator doesn't have to hit Refresh every load. We watch the tab
// switcher for a change; 01-tab-switching.js fires custom events on
// activation, but as a safety net we ALSO fire on the very first
// tick after DOMContentLoaded if #tab-doctor is currently visible.
(function () {
  let ran = false;
  function _once() {
    if (ran) return;
    const t = document.getElementById("tab-doctor");
    if (t && t.style.display !== "none") {
      ran = true;
      try { doctorLoadHardware(); } catch (_) {}
    }
  }
  document.addEventListener("click", (ev) => {
    if (!ev || !ev.target) return;
    const target = ev.target.closest && ev.target.closest('[onclick*="doctor" i], [onclick*="Doctor" i], .tab-btn');
    if (target) setTimeout(_once, 50);
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(_once, 500), {once: true});
  } else {
    setTimeout(_once, 500);
  }
})();
