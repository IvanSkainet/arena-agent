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

// v3.91.0: `_hwEsc` now comes from 03-helpers.js (aliased to esc()).
// This file used to redefine it locally; that duplicate is gone so
// there's one HTML-escape function in the whole Dashboard.

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
  // Deduplicate by device: btrfs subvolumes report the same /dev/dm-0
  // mounted at /, /home, /srv, /root, /var/cache, /var/log, /var/tmp
  // — showing seven identical "58 GB free of 224.8 GB" rows is noise.
  // Group by device: primary label = first mount, extras collapse into
  // an appended "(+N more)" hint.
  const byDevice = new Map();
  disks.forEach(d => {
    const key = d.device || d.mount || "?";
    if (!byDevice.has(key)) {
      byDevice.set(key, {primary: d, mounts: [d.mount].filter(Boolean)});
    } else {
      if (d.mount) byDevice.get(key).mounts.push(d.mount);
    }
  });
  const rows = Array.from(byDevice.values()).slice(0, 12).map(({primary: d, mounts}) => {
    const extraMounts = mounts.length > 1 ? " (+" + (mounts.length - 1) + " more mounts)" : "";
    const label = _hwEsc((d.mount || d.device || "?") + extraMounts);
    const used = (d.used_gb != null && d.total_gb)
      ? _hwFmtGB(d.used_gb) + " / " + _hwFmtGB(d.total_gb) + " · " + Math.round(d.used_pct || 0) + "%"
      : "—";
    const bar = (d.used_pct != null)
      ? '<div style="height:4px;background:var(--bg);border-radius:2px;overflow:hidden;margin-top:2px"><div style="height:4px;background:' + (d.used_pct > 90 ? "var(--red)" : d.used_pct > 75 ? "var(--orange)" : "var(--green)") + ';width:' + Math.min(100, d.used_pct) + '%"></div></div>'
      : '';
    return [label, used + bar];
  });
  return _hwCard("Storage (" + byDevice.size + " unique device" + (byDevice.size === 1 ? "" : "s") + ")", rows);
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

function _hwRenderKernelModules(km) {
  if (!km || !km.available) return "";
  const total = km.count || 0;
  const rows = (km.modules || []).slice(0, 12).map(m => [
    _hwEsc(m.name),
    _hwFmtNumber(m.size_bytes / 1024, 0) + " KB · used by " + (m.used_count || 0),
  ]);
  if (!rows.length) return "";
  // Card header must match the shown row count, not the raw payload
  // length (v3.88.4 said "top 156" but only rendered 12).
  return _hwCard("Kernel modules (" + total + " loaded, top " + rows.length + " by size)", rows);
}

function _hwRenderContainers(c) {
  if (!c || !c.available) return "";
  const rows = [];
  (c.containers || []).slice(0, 15).forEach(x => {
    const meta = x.status + (x.ports ? " · " + x.ports.slice(0, 40) : "");
    rows.push([_hwEsc(x.name), _hwEsc(meta)]);
  });
  const label = "Containers (" + (c.runtime || "?") + ", "
              + (c.running_count || 0) + "/" + (c.total_count || 0) + " running)";
  if (!rows.length) return _hwCard(label, [["state", "no containers"]]);
  return _hwCard(label, rows);
}

function _hwRenderSystemdTimers(t) {
  if (!t || !t.available) return "";
  const rows = (t.timers || []).slice(0, 15).map(x => [
    _hwEsc(x.unit),
    (x.next ? "next: " + _hwEsc(x.next) : "—")
      + (x.last ? " · last: " + _hwEsc(x.last) : ""),
  ]);
  if (!rows.length) return "";
  return _hwCard("Systemd timers (" + rows.length + " shown)", rows);
}

function _hwRenderNetworkIO(nio) {
  if (!nio || !nio.available) return "";
  const rows = [];
  (nio.interfaces || []).forEach(i => {
    const parts = [
      "↓ " + _hwFmtBytes(i.bytes_recv),
      "↑ " + _hwFmtBytes(i.bytes_sent),
    ];
    if (i.errin || i.errout) parts.push("err " + (i.errin + i.errout));
    if (i.dropin || i.dropout) parts.push("drop " + (i.dropin + i.dropout));
    rows.push([_hwEsc(i.name), parts.join(" · ")]);
  });
  if (!rows.length) return "";
  return _hwCard("Network I/O (cumulative)", rows);
}

function _hwFmtBytes(n) {
  if (n == null || Number.isNaN(n)) return "—";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
  if (n < 1099511627776) return (n / 1073741824).toFixed(2) + " GB";
  return (n / 1099511627776).toFixed(2) + " TB";
}

function _hwRenderUpdates(u) {
  if (!u || !u.available) return "";
  const rows = [
    ["Manager", _hwEsc(u.manager || "?")],
    ["Pending", (u.pending_count != null ? String(u.pending_count) : "?")
                + (u.checked_at ? " · checked " + _hwEsc(u.checked_at) : "")],
  ];
  if (u.error) rows.push(["Note", _hwEsc(u.error)]);
  (u.sample || []).slice(0, 8).forEach(pkg => {
    rows.push(["  " + _hwEsc(pkg.name || pkg), _hwEsc(pkg.new_version || "")]);
  });
  return _hwCard("Package updates available", rows);
}

function _hwRenderLoggedUsers(lu) {
  if (!lu || !lu.available) return "";
  const rows = (lu.users || []).map(u => [
    _hwEsc(u.name || "?"),
    _hwEsc(u.terminal || "") + (u.host ? " from " + _hwEsc(u.host) : "")
      + (u.started ? " · " + _hwEsc(u.started) : ""),
  ]);
  if (!rows.length) return _hwCard("Logged-in users", [["state", "no active sessions"]]);
  return _hwCard("Logged-in users (" + rows.length + ")", rows);
}

function _hwRenderCpuVulns(v) {
  if (!v || !v.available) return "";
  const rows = [];
  Object.entries(v.mitigations || {}).forEach(([name, status]) => {
    const short = String(status || "").split(";")[0].trim();
    let label = short;
    if (/vulnerable/i.test(short)) label = "⚠️ " + short;
    else if (/mitigation/i.test(short) || /not affected/i.test(short)) label = "✓ " + short;
    rows.push([_hwEsc(name), _hwEsc(label)]);
  });
  if (!rows.length) return "";
  return _hwCard("CPU vulnerabilities (mitigation status)", rows);
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


// v3.88.4 renderers -------------------------------------------------

function _hwRenderVirt(v) {
  if (!v || !v.available) return "";
  const rows = [["Type", _hwEsc(v.type || "unknown")]];
  if (v.hypervisor) rows.push(["Hypervisor", _hwEsc(v.hypervisor)]);
  if (v.container) rows.push(["Container", _hwEsc(v.container)]);
  if (v.model) rows.push(["Model", _hwEsc(v.model)]);
  return _hwCard("Virtualization", rows);
}

function _hwRenderTimeSync(t) {
  if (!t || !t.available) return "";
  const rows = [];
  const keys = ["NTPSynchronized", "ntp_synchronized", "server",
                "reference_time", "offset", "stratum", "leap_status",
                "Timezone", "poll_interval"];
  keys.forEach(k => { if (t[k]) rows.push([_hwEsc(k), _hwEsc(t[k])]); });
  if (!rows.length && t.output) rows.push(["output", _hwEsc(t.output.slice(0, 300))]);
  return rows.length ? _hwCard("Time sync (NTP)", rows) : "";
}

function _hwRenderFirewall(f) {
  if (!f || !f.available) return "";
  const rows = [
    ["Backend", _hwEsc(f.backend || "?")],
    ["Active", f.active ? "yes" : "no"],
  ];
  if (f.profiles) {
    f.profiles.forEach(p => rows.push([_hwEsc(p.name),
                                        p.enabled ? "enabled" : "disabled"]));
  }
  Object.entries(f.rule_summary || {}).forEach(([k, v]) =>
    rows.push([_hwEsc(k), _hwEsc(String(v))]));
  return _hwCard("Firewall", rows);
}

function _hwRenderDns(d) {
  if (!d || !d.available) return "";
  const rows = [];
  (d.nameservers || []).forEach((ns, i) => rows.push(["ns" + (i + 1), _hwEsc(ns)]));
  if (d.search && d.search.length) rows.push(["search", _hwEsc(d.search.join(" "))]);
  if (d.hosts_entry_count != null) rows.push(["/etc/hosts", d.hosts_entry_count + " entries"]);
  return rows.length ? _hwCard("DNS resolvers", rows) : "";
}

function _hwRenderEnvSecrets(es) {
  if (!es || !es.available) return "";
  const rows = [["Credentials", String(es.count || 0)]];
  (es.names || []).slice(0, 20).forEach(n => rows.push(["", _hwEsc(n)]));
  const files = es.file_refs || [];
  if (files.length) {
    rows.push(["Files ↓", String(files.length)]);
    files.slice(0, 10).forEach(n => rows.push(["", _hwEsc(n)]));
  }
  return _hwCard("Env secret NAMES (values never exposed)", rows);
}

function _hwRenderVenvs(v) {
  if (!v || !v.available) return "";
  const rows = [];
  (v.venvs || []).forEach(env => {
    rows.push([_hwEsc((env.python_version || "?").split(" ")[0]),
               _hwEsc(env.path) + " · " + (env.package_count || 0) + " pkgs"]);
  });
  return rows.length ? _hwCard("Python venvs (" + rows.length + ")", rows) : "";
}

function _hwRenderGitRepos(g) {
  if (!g || !g.available) return "";
  const rows = [];
  (g.repos || []).forEach(r => {
    const parts = [_hwEsc(r.branch || "?")];
    if (r.dirty_files != null) parts.push(r.dirty_files + " dirty");
    if (r.ahead != null && r.behind != null) parts.push("↑" + r.ahead + " ↓" + r.behind);
    rows.push([_hwEsc(r.path.split("/").slice(-1)[0]), parts.join(" · ")]);
    if (r.last_commit) rows.push(["  last", _hwEsc(r.last_commit)]);
  });
  return rows.length ? _hwCard("Git repos (" + (g.repos || []).length + ")", rows) : "";
}

function _hwRenderCrontab(c) {
  if (!c || !c.available) return "";
  const rows = [];
  (c.user_entries || []).forEach(e => rows.push(["user", _hwEsc(e)]));
  (c.system_entries || []).slice(0, 15).forEach(e => rows.push(["sys", _hwEsc(e)]));
  if (!rows.length) return _hwCard("Crontab", [["state", "no cron entries"]]);
  return _hwCard("Crontab (" + rows.length + ")", rows);
}

function _hwRenderKernelErrors(k) {
  if (!k || !k.available) return "";
  const rows = (k.errors || []).slice(0, 15).map((e, i) =>
    [String(i + 1), _hwEsc(e)]);
  if (!rows.length) return _hwCard("Kernel errors (last)", [["state", "clean 🎉"]]);
  return _hwCard("Kernel errors (last " + rows.length + ")", rows);
}

function _hwRenderJournalErrors(j) {
  if (!j || !j.available) return "";
  const rows = (j.errors || []).slice(0, 15).map((e, i) =>
    [String(i + 1), _hwEsc(e)]);
  if (!rows.length) return _hwCard("Journal errors (last hour)",
                                     [["state", "clean 🎉"]]);
  return _hwCard("Journal errors (last hour, " + rows.length + " shown)", rows);
}

// =====================================================================
// v3.89.0 unified renderer.
//
// _HW_CARD_MAP is the single source of truth for "which registry
// section maps to which _hwRender* function AND how to extract the
// data from the source object". Both the Doctor tab and the Full
// Inventory tab call _hwRenderAll(source, wantSet) with:
//
//   * source  -- an object that has every section as a top-level key
//                (matches both /v1/hardware.hardware AND /v1/inventory).
//   * wantSet -- Set of section names to include, or null = all.
//
// Adding a new probe? One line in _HW_CARD_MAP below and both tabs
// pick it up. If the section already comes with matching key names,
// the default `extract` is fine.
// =====================================================================

// Prefer the normalized shape when it's meaningfully different from
// the raw one. Doctor always gets the normalized shape from
// /v1/hardware; Full Inventory can pass either one -- the extractor
// tolerates both by preferring normalized (`hw`) when available.
const _HW_CARD_MAP = [
  // 'os' section from the registry -- rendered by _hwRenderOS which
  // shows OS/distro/kernel/uptime. Named 'os' so it matches the
  // registry key exactly (identity is a separate section).
  {name: "os",               extract: s => s.os,               render: _hwRenderOS},
  {name: "boot_time",        extract: s => s.boot_time,        render: _hwRenderBoot},
  {name: "cpu",              extract: s => s.cpu,              render: _hwRenderCPU},
  {name: "memory",           extract: s => s.memory,           render: _hwRenderMemory},
  {name: "gpu",              extract: s => ({one: s.gpu && s.gpu.name ? s.gpu : (s.gpus && s.gpus[0]) || (s.gpu && s.gpu.gpus && s.gpu.gpus[0]) || null,
                                              all: (s.gpus && s.gpus.length ? s.gpus : (s.gpu && s.gpu.gpus) || [])}),
                              render: v => _hwRenderGPU(v.one, v.all)},
  {name: "disks",            extract: s => s.disks,            render: _hwRenderDisks},
  {name: "thermal_detail",   extract: s => ({legacy: s.thermal, detail: s.thermal_detail}),
                              render: v => _hwRenderThermal(v.legacy, v.detail)},
  {name: "fans",             extract: s => s.fans,             render: _hwRenderFans},
  {name: "battery",          extract: s => s.battery,          render: _hwRenderBattery},
  {name: "disk_smart",       extract: s => s.disk_smart,       render: _hwRenderSmart},
  {name: "audio",            extract: s => s.audio,            render: _hwRenderAudio},
  {name: "motherboard",      extract: s => ({mb: s.motherboard && s.motherboard.motherboard ? s.motherboard.motherboard : s.motherboard,
                                              bios: s.bios || (s.motherboard && s.motherboard.bios)}),
                              render: v => _hwRenderMotherboard(v.mb, v.bios)},
  {name: "network",          extract: s => s.network,          render: _hwRenderNetwork},
  {name: "top_processes",    extract: s => s.top_processes,    render: _hwRenderTopProcesses},
  {name: "listening_ports",  extract: s => s.listening_ports,  render: _hwRenderListeningPorts},
  {name: "systemd_failed",   extract: s => s.systemd_failed,   render: _hwRenderSystemdFailed},
  {name: "containers",       extract: s => s.containers,       render: _hwRenderContainers},
  {name: "systemd_timers",   extract: s => s.systemd_timers,   render: _hwRenderSystemdTimers},
  {name: "network_io",       extract: s => s.network_io,       render: _hwRenderNetworkIO},
  {name: "updates_available",extract: s => s.updates_available,render: _hwRenderUpdates},
  {name: "logged_users",     extract: s => s.logged_users,     render: _hwRenderLoggedUsers},
  {name: "cpu_vulnerabilities", extract: s => s.cpu_vulnerabilities, render: _hwRenderCpuVulns},
  {name: "virtualization",   extract: s => s.virtualization,   render: _hwRenderVirt},
  {name: "time_sync",        extract: s => s.time_sync,        render: _hwRenderTimeSync},
  {name: "firewall_status",  extract: s => s.firewall_status,  render: _hwRenderFirewall},
  {name: "dns_resolvers",    extract: s => s.dns_resolvers,    render: _hwRenderDns},
  {name: "env_secret_names", extract: s => s.env_secret_names, render: _hwRenderEnvSecrets},
  {name: "python_venvs",     extract: s => s.python_venvs,     render: _hwRenderVenvs},
  {name: "git_repos",        extract: s => s.git_repos,        render: _hwRenderGitRepos},
  {name: "crontab_entries",  extract: s => s.crontab_entries,  render: _hwRenderCrontab},
  {name: "dmesg_errors",     extract: s => s.dmesg_errors,     render: _hwRenderKernelErrors},
  {name: "journal_errors",   extract: s => s.journal_errors,   render: _hwRenderJournalErrors},
  {name: "services",         extract: s => s.services,         render: _hwRenderServices},
  {name: "kernel_modules",   extract: s => s.kernel_modules,   render: _hwRenderKernelModules},
  // Extra runtime bundles: runtimes / package_managers / browsers.
  // _hwRenderExtra reads them all from a single flat object.
  {name: "__extra__",        extract: s => s,                  render: _hwRenderExtra},
];

// Render every section from `source` that (a) has an extractor and
// (b) either is unfiltered or is in `wantSet`. Returns concatenated
// HTML (may be empty string if nothing renders).
function _hwRenderAll(source, wantSet) {
  if (!source || typeof source !== "object") return "";
  const out = [];
  _HW_CARD_MAP.forEach(entry => {
    if (wantSet && !wantSet.has(entry.name) && entry.name !== "__extra__") return;
    try {
      const data = entry.extract(source);
      if (data === undefined || data === null) return;
      const html = entry.render(data);
      if (html) out.push(html);
    } catch (e) {
      // Render errors must never break the whole grid; swallow +
      // console.warn so a broken renderer isolates to one card.
      if (window && window.console) console.warn("hw card failed", entry.name, e);
    }
  });
  return out.join("");
}

// Public helper: fetch the registry once at boot and cache it. Full
// Inventory uses this to auto-build the checkbox strip; without the
// endpoint (older bridge / offline) it falls back to the map above.
window._hwRegistry = null;
async function _hwLoadRegistry() {
  if (window._hwRegistry) return window._hwRegistry;
  try {
    const r = await api("/v1/inventory/registry");
    if (r && r.ok && Array.isArray(r.sections)) {
      window._hwRegistry = r.sections;
      return r.sections;
    }
  } catch (_e) { /* fall through */ }
  // Fallback derived from the card map.
  window._hwRegistry = _HW_CARD_MAP
    .filter(e => e.name !== "__extra__")
    .map(e => ({name: e.name, label: e.name, category: "hardware", show_in_doctor: true}));
  return window._hwRegistry;
}
