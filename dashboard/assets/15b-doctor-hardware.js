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
      + '<td style="padding:2px 8px 2px 0;color:var(--text2);vertical-align:top;white-space:nowrap;font-size:12px">'
      + _hwEsc(k) + '</td>'
      + '<td style="padding:2px 0;font-size:12px;word-break:break-word;color:var(--text)">' + v + '</td>'
      + '</tr>';
  }).join("");
  return '<div class="hw-card" style="border:1px solid var(--accent);border-radius:6px;padding:10px;background:var(--bg3)">'
    + '<div style="font-weight:600;margin-bottom:6px;font-size:13px;color:var(--blue)">' + _hwEsc(title) + '</div>'
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
  const bar = (mem.total_gb && mem.used_gb) ? '<div style="height:6px;background:var(--bg);border-radius:3px;overflow:hidden;margin-top:4px"><div style="height:6px;background:var(--blue);width:' + Math.min(100, Math.round((mem.used_gb / mem.total_gb) * 100)) + '%"></div></div>' : '';
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
      ? '<div style="height:4px;background:var(--bg);border-radius:2px;overflow:hidden;margin-top:2px"><div style="height:4px;background:' + (d.used_pct > 90 ? "var(--red)" : d.used_pct > 75 ? "var(--orange)" : "var(--green)") + ';width:' + Math.min(100, d.used_pct) + '%"></div></div>'
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

function _hwRenderThermal(thermal, thermalDetail) {
  // v3.88.1: prefer the classified thermal_detail probe when it has
  // data. Falls back to legacy thermal.temperatures[] arrays. The
  // pre-v3.88 code path used to render "[object Object]" because it
  // passed the raw {temperatures, lm_sensors} envelope to string
  // coercion; that is fixed here.
  const rows = [];
  if (thermalDetail && thermalDetail.available && Array.isArray(thermalDetail.sensors)) {
    thermalDetail.sensors.slice(0, 20).forEach((s) => {
      let extra = "";
      if (s.critical_c && s.critical_c < 200) extra = " (crit " + s.critical_c + ")";
      else if (s.high_c && s.high_c < 200) extra = " (high " + s.high_c + ")";
      const label = "[" + (s.class || "other") + "] " + _hwEsc(s.label || s.chip || "?");
      rows.push([label, (s.celsius != null ? s.celsius + " °C" + extra : "—")]);
    });
  } else if (thermal && Array.isArray(thermal.temperatures)) {
    thermal.temperatures.slice(0, 12).forEach((t) => {
      rows.push([_hwEsc(t.type || t.source || "?"),
                 (t.celsius != null ? t.celsius + " °C" : "—")]);
    });
  } else if (Array.isArray(thermal)) {
    thermal.slice(0, 10).forEach((t) => {
      rows.push([_hwEsc(t.name || t.label || "?"),
                 (t.temp_c != null ? t.temp_c + " °C" : "—")]);
    });
  }
  return rows.length ? _hwCard("Thermal sensors", rows) : "";
}

function _hwRenderFans(fans) {
  if (!fans || !fans.available) return "";
  const rows = (fans.fans || []).map(f =>
    [_hwEsc(f.label || f.chip || "?"), (f.rpm != null ? f.rpm + " RPM" : "—")]);
  return rows.length ? _hwCard("Fans", rows) : "";
}

function _hwRenderBattery(battery) {
  if (!battery || !battery.available) return "";
  const rows = [];
  if (battery.percent != null) {
    rows.push(["Charge", battery.percent + "% " +
                          (battery.plugged ? "(AC)" : "(discharging)")]);
  }
  (battery.batteries || []).forEach(bat => {
    const parts = [bat.manufacturer, bat.model_name, bat.technology].filter(Boolean);
    if (parts.length) rows.push(["Device", _hwEsc(parts.join(" / "))]);
    if (bat.health_pct != null) rows.push(["Health", bat.health_pct + "%"]);
    if (bat.cycle_count != null) rows.push(["Cycles", String(bat.cycle_count)]);
  });
  return rows.length ? _hwCard("Battery", rows) : "";
}

function _hwRenderAudio(audio) {
  if (!audio || !audio.available) return "";
  const rows = [];
  (audio.sinks || []).slice(0, 10).forEach(s => rows.push(["Out", _hwEsc(s.name || "")]));
  (audio.sources || []).slice(0, 10).forEach(s => rows.push(["In", _hwEsc(s.name || "")]));
  return rows.length ? _hwCard("Audio", rows) : "";
}

function _hwRenderSmart(smart) {
  if (!smart || !smart.available) return "";
  const rows = [];
  (smart.devices || []).forEach(d => {
    const status = d.passed === true ? "PASS"
                 : d.passed === false ? "FAIL"
                 : "?";
    const model = _hwEsc(d.model || "(unknown)");
    rows.push([_hwEsc(d.device || "?"), status + " · " + model]);
    if (d.temperature_c != null) rows.push(["  temp", d.temperature_c + " °C"]);
    if (d.power_on_hours != null) rows.push(["  hours", String(d.power_on_hours)]);
    if (d.percent_used != null) rows.push(["  wear", d.percent_used + "%"]);
    if (d.reallocated_sectors != null) rows.push(["  reallocated", String(d.reallocated_sectors)]);
    if (d.error) {
      rows.push(["  error", '<span style="color:var(--red)">' + _hwEsc(d.error) + "</span>"]);
    }
    if (d.hint) {
      rows.push(["  hint", '<span style="color:var(--warning-text);font-size:11px">' + _hwEsc(d.hint) + "</span>"]);
    }
  });
  return rows.length ? _hwCard("Disk SMART", rows) : "";
}

function _hwRenderTopProcesses(top) {
  if (!top || !top.available) return "";
  const rows = [];
  (top.by_cpu || []).slice(0, 5).forEach(p => {
    rows.push(["CPU " + _hwEsc(p.name),
               p.cpu_pct + "% · " + p.rss_mb + " MB · pid " + p.pid]);
  });
  (top.by_memory || []).slice(0, 5).forEach(p => {
    rows.push(["RAM " + _hwEsc(p.name),
               p.rss_mb + " MB · " + p.cpu_pct + "% CPU · pid " + p.pid]);
  });
  return rows.length ? _hwCard("Top processes (top 5 by CPU + by RAM)", rows) : "";
}

function _hwRenderListeningPorts(lp) {
  if (!lp || !lp.available) return "";
  const rows = [];
  (lp.tcp || []).forEach(p => {
    rows.push(["tcp/" + p.port,
               _hwEsc((p.process || "?") + " · pid " + (p.pid || "?") + " · " + p.addr)]);
  });
  return rows.length ? _hwCard("Listening TCP ports (" + (lp.tcp||[]).length + ")", rows) : "";
}

function _hwRenderSystemdFailed(sf) {
  if (!sf || !sf.available) return "";
  const rows = [];
  (sf.system_failed || []).forEach(u =>
    rows.push(["system", _hwEsc(u.unit) + " — " + _hwEsc(u.description || "")]));
  (sf.user_failed || []).forEach(u =>
    rows.push(["user", _hwEsc(u.unit) + " — " + _hwEsc(u.description || "")]));
  if (!rows.length) {
    return _hwCard("Systemd failed units", [["all", "no failed units 🎉"]]);
  }
  return _hwCard("Systemd failed units (" + rows.length + ")", rows);
}

function _hwRenderBoot(boot) {
  if (!boot || !boot.available) return "";
  const days = Math.floor((boot.uptime_seconds || 0) / 86400);
  const hours = Math.floor(((boot.uptime_seconds || 0) % 86400) / 3600);
  const rows = [
    ["Booted at", _hwEsc((boot.boot_time_iso || "").replace("T", " ").split(".")[0])],
    ["Uptime", days + "d " + hours + "h"],
  ];
  return _hwCard("Boot", rows);
}

function _hwRenderServices(services) {
  // Collapsible + scrollable list -- no more "and 33 more" tail.
  if (!services || typeof services !== "object") return "";
  const parts = [];
  Object.entries(services).forEach(([groupName, arr]) => {
    if (!Array.isArray(arr) || !arr.length) return;
    const items = arr.map(name => "<li>" + _hwEsc(String(name)) + "</li>").join("");
    parts.push(
      '<details style="margin-top:6px">'
      + '<summary style="cursor:pointer;font-size:12px;color:var(--text2)">'
      + _hwEsc(groupName) + " (" + arr.length + ")"
      + '</summary>'
      + '<ul style="margin:4px 0 4px 20px;max-height:220px;overflow-y:auto;'
      + 'font-family:var(--mono);font-size:11px;line-height:1.5">'
      + items + "</ul>"
      + "</details>"
    );
  });
  if (!parts.length) return "";
  return '<div class="card" style="margin-bottom:10px">'
       + '<div style="font-weight:600;margin-bottom:6px;font-size:13px;color:var(--blue)">Services</div>'
       + parts.join("")
       + "</div>";
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
  if (target) target.innerHTML = '<div style="color:var(--text3);font-size:12px">Loading hardware inventory…</div>';
  try {
    const r = await api("/v1/hardware");
    if (!r || r.ok !== true) {
      target.innerHTML = '<div style="color:var(--red)">Hardware fetch failed: ' + _hwEsc((r && r.error) || "unknown") + '</div>';
      return;
    }
    const hw = r.hardware || {};
    if (timeEl && hw.generated_at) {
      timeEl.textContent = "collected " + new Date(hw.generated_at).toLocaleString();
    }
    const cards = [
      _hwRenderOS(hw.os),
      _hwRenderBoot(hw.boot_time),
      _hwRenderCPU(hw.cpu),
      _hwRenderMemory(hw.memory),
      _hwRenderGPU(hw.gpu, hw.gpus),
      _hwRenderDisks(hw.disks),
      _hwRenderThermal(hw.thermal, hw.thermal_detail),
      _hwRenderFans(hw.fans),
      _hwRenderBattery(hw.battery),
      _hwRenderSmart(hw.disk_smart),
      _hwRenderAudio(hw.audio),
      _hwRenderMotherboard(hw.motherboard, hw.bios),
      _hwRenderNetwork(hw.network),
      _hwRenderTopProcesses(hw.top_processes),
      _hwRenderListeningPorts(hw.listening_ports),
      _hwRenderSystemdFailed(hw.systemd_failed),
      _hwRenderServices(hw.services),
      _hwRenderExtra(hw),
    ].filter(Boolean);
    if (!cards.length) {
      target.innerHTML = '<div style="color:var(--warning-text)">Backend returned empty hardware payload.</div>';
    } else {
      target.innerHTML = cards.join("");
    }
    if (rawEl) rawEl.textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    target.innerHTML = '<div style="color:var(--red)">Hardware fetch failed: ' + _hwEsc(e && e.message || e) + '</div>';
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
