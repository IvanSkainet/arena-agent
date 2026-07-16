function formatInventoryText(inv, onlySections) {
  const lines = [];
  const wantAll = !onlySections || onlySections.length === 0;
  const want = new Set(onlySections || []);
  function show(name) { return wantAll || want.has(name); }

  if (inv.generated_at) lines.push(`generated_at: ${inv.generated_at}`);
  lines.push("");

  if (show("identity") && inv.identity) {
    lines.push("### Identity");
    const i = inv.identity;
    lines.push(`  user: ${i.user}   host: ${i.hostname}`);
    lines.push(`  home: ${i.home}`);
    if (i.shell) lines.push(`  shell: ${i.shell}`);
    lines.push("");
  }
  if (show("os") && inv.os) {
    const o = inv.os;
    lines.push("### OS");
    lines.push(`  ${o.system} ${o.release} (${o.machine})`);
    if (o.distro?.pretty) lines.push(`  distro: ${o.distro.pretty}`);
    if (o.caption) lines.push(`  edition: ${o.caption}  build ${o.build_number||""}`);
    if (o.uptime_seconds) {
      const u = o.uptime_seconds;
      const d = Math.floor(u/86400), h = Math.floor((u%86400)/3600), m = Math.floor((u%3600)/60);
      lines.push(`  uptime: ${d}d ${h}h ${m}m`);
    }
    lines.push(`  python: ${o.python_version}`);
    lines.push("");
  }
  if (show("cpu") && inv.cpu) {
    const c = inv.cpu;
    lines.push("### CPU");
    lines.push(`  ${c.name || "(unknown)"}`);
    lines.push(`  ${c.cores_physical || "?"} physical / ${c.cores_logical || "?"} logical cores${c.max_ghz?(", "+c.max_ghz+" GHz max"):""}`);
    if (c.load_avg) lines.push(`  load avg: ${c.load_avg.map(x=>x.toFixed(2)).join(", ")}`);
    lines.push("");
  }
  if (show("memory") && inv.memory) {
    const m = inv.memory;
    lines.push("### Memory");
    if (m.total_gb) {
      lines.push(`  ${m.total_gb} GB total, ${m.used_gb||"?"} GB used, ${m.available_gb||"?"} GB free`);
    }
    if (m.swap_total_gb) lines.push(`  swap: ${m.swap_free_gb||0} free / ${m.swap_total_gb} GB`);
    (m.modules||[]).forEach((mod,i) => {
      let s = `  slot ${i+1}: ${mod.size_gb} GB`;
      if (mod.speed_mhz) s += ` @ ${mod.speed_mhz} MHz`;
      if (mod.manufacturer) s += ` — ${mod.manufacturer}`;
      if (mod.part_number) s += ` (${mod.part_number})`;
      lines.push(s);
    });
    lines.push("");
  }
  if (show("motherboard") && inv.motherboard) {
    const mb = inv.motherboard;
    if (mb.motherboard) {
      lines.push("### Motherboard");
      lines.push(`  ${mb.motherboard.manufacturer || ""} ${mb.motherboard.product || ""}`);
      if (mb.motherboard.version) lines.push(`  rev ${mb.motherboard.version}`);
      lines.push("");
    }
    if (mb.bios) {
      lines.push("### BIOS");
      lines.push(`  ${mb.bios.manufacturer || ""} v${mb.bios.version || ""}${mb.bios.release_date?" ("+mb.bios.release_date+")":""}`);
      lines.push("");
    }
  }
  if (show("gpu") && inv.gpu) {
    lines.push("### GPU");
    (inv.gpu.gpus||[]).forEach(g => {
      let s = `  • ${g.name}`;
      if (g.vram_mb) s += ` (${(g.vram_mb/1024).toFixed(1)} GB VRAM)`;
      if (g.driver_version) s += ` — driver ${g.driver_version}`;
      lines.push(s);
    });
    (inv.gpu.nvidia||[]).forEach(n => {
      lines.push(`  NVIDIA: ${n.name} — ${n.vram_used_mb}/${n.vram_total_mb} MB used, ${n.temperature_c}°C, ${n.utilization_pct}% util`);
    });
    lines.push("");
  }
  if (show("disks") && inv.disks) {
    lines.push("### Disks");
    inv.disks.forEach(d => {
      lines.push(`  ${(d.device||"").padEnd(10)} ${(d.mount||"").padEnd(15)} ${(d.filesystem||"").padEnd(8)} ${d.free_gb}/${d.total_gb} GB free (${d.used_pct}% used)`);
    });
    lines.push("");
  }
  if (show("thermal_detail") && inv.thermal_detail && inv.thermal_detail.available) {
    lines.push("### Thermal (per-source)");
    const byCls = {};
    (inv.thermal_detail.sensors||[]).forEach(s => {
      const c = s.class || "other";
      (byCls[c] = byCls[c] || []).push(s);
    });
    ["cpu","gpu","nvme","board","other"].forEach(cls => {
      (byCls[cls]||[]).forEach(s => {
        let extra = "";
        if (s.critical_c) extra = ` (crit ${s.critical_c}°C)`;
        else if (s.high_c) extra = ` (high ${s.high_c}°C)`;
        lines.push(`  [${cls}] ${s.label}: ${s.celsius}°C${extra}`);
      });
    });
    lines.push("");
  }
  if (show("fans") && inv.fans && inv.fans.available) {
    lines.push("### Fans");
    (inv.fans.fans||[]).forEach(f => {
      lines.push(`  ${f.label}: ${f.rpm} RPM`);
    });
    lines.push("");
  }
  if (show("battery") && inv.battery && inv.battery.available) {
    const b = inv.battery;
    lines.push("### Battery");
    if (b.percent !== undefined && b.percent !== null) {
      lines.push(`  Charge   : ${b.percent}% (${b.plugged ? "AC" : "discharging"})`);
    }
    (b.batteries||[]).forEach(bat => {
      const parts = [bat.manufacturer, bat.model_name, bat.technology].filter(Boolean);
      if (parts.length) lines.push(`  Device   : ${parts.join(" / ")}`);
      if (bat.health_pct !== undefined) lines.push(`  Health   : ${bat.health_pct}%`);
      if (bat.cycle_count !== undefined) lines.push(`  Cycles   : ${bat.cycle_count}`);
    });
    lines.push("");
  }
  if (show("disk_smart") && inv.disk_smart && inv.disk_smart.available) {
    lines.push("### Disk SMART");
    (inv.disk_smart.devices||[]).forEach(d => {
      const status = d.passed === true ? "PASS" : d.passed === false ? "FAIL" : "?";
      lines.push(`  ${d.device} [${status}] ${d.model||""}`);
      const details = [];
      if (d.temperature_c !== undefined) details.push(`temp ${d.temperature_c}°C`);
      if (d.power_on_hours !== undefined) details.push(`${d.power_on_hours} h`);
      if (d.percent_used !== undefined) details.push(`${d.percent_used}% used`);
      if (d.available_spare_pct !== undefined) details.push(`${d.available_spare_pct}% spare`);
      if (d.reallocated_sectors !== undefined) details.push(`${d.reallocated_sectors} reallocated`);
      if (details.length) lines.push(`    ${details.join(" · ")}`);
      // v4.0.2: surface the per-device error + operator hint so the
      // rendered inventory view isn't a silent "?" when the bridge
      // lacks permission to read SMART data.
      if (d.error) lines.push(`    error: ${d.error}`);
      if (d.hint)  lines.push(`    hint:  ${d.hint}`);
    });
    lines.push("");
  }
  if (show("audio") && inv.audio && inv.audio.available) {
    lines.push("### Audio");
    (inv.audio.sinks||[]).slice(0,10).forEach(s => lines.push(`  out: ${s.name||""}`));
    (inv.audio.sources||[]).slice(0,10).forEach(s => lines.push(`  in : ${s.name||""}`));
    lines.push("");
  }
  if (show("top_processes") && inv.top_processes && inv.top_processes.available) {
    lines.push("### Top processes (by CPU / by RAM)");
    (inv.top_processes.by_cpu||[]).slice(0,5).forEach(p =>
      lines.push(`  cpu ${p.cpu_pct.toString().padStart(5)}%  ${(p.rss_mb+" MB").padStart(10)}  ${p.name} (pid ${p.pid})`));
    (inv.top_processes.by_memory||[]).slice(0,5).forEach(p =>
      lines.push(`  ram ${(p.rss_mb+" MB").padStart(10)}  ${p.cpu_pct.toString().padStart(5)}%  ${p.name} (pid ${p.pid})`));
    lines.push("");
  }
  if (show("listening_ports") && inv.listening_ports && inv.listening_ports.available) {
    const tcp = inv.listening_ports.tcp || [];
    lines.push(`### Listening TCP ports (${tcp.length})`);
    tcp.slice(0,25).forEach(p =>
      lines.push(`  tcp/${p.port.toString().padEnd(6)} ${(p.process||"").padEnd(20)} pid ${p.pid||"?"}  ${p.addr||""}`));
    lines.push("");
  }
  if (show("systemd_failed") && inv.systemd_failed && inv.systemd_failed.available) {
    const failed = (inv.systemd_failed.system_failed||[]).concat(inv.systemd_failed.user_failed||[]);
    lines.push(`### Systemd failed units (${failed.length})`);
    if (failed.length === 0) lines.push("  (none — clean state)");
    failed.slice(0,20).forEach(u =>
      lines.push(`  ${u.unit} — ${u.description||""}`));
    lines.push("");
  }
  if (show("boot_time") && inv.boot_time && inv.boot_time.available) {
    const up = inv.boot_time.uptime_seconds || 0;
    const d = Math.floor(up/86400), h = Math.floor((up%86400)/3600), m = Math.floor((up%3600)/60);
    lines.push("### Boot");
    lines.push(`  Booted   : ${inv.boot_time.boot_time_iso||""}`);
    lines.push(`  Uptime   : ${d}d ${h}h ${m}m`);
    lines.push("");
  }
  if (show("kernel_modules") && inv.kernel_modules && inv.kernel_modules.available) {
    const km = inv.kernel_modules;
    lines.push(`### Kernel modules (${km.count||0} loaded, showing top ${(km.modules||[]).length})`);
    (km.modules||[]).slice(0,15).forEach(mod =>
      lines.push(`  ${mod.name.padEnd(28)} ${String(mod.size_bytes).padStart(10)} B  used by ${mod.used_count}`));
    lines.push("");
  }
  if (show("network") && inv.network) {
    const n = inv.network;
    lines.push("### Network");
    lines.push(`  hostname: ${n.hostname}  fqdn: ${n.fqdn||""}`);
    (n.interfaces||[]).forEach(i => {
      lines.push(`  ${(i.name||"").padEnd(28)} ${i.ipv4||""}`);
    });
    lines.push("");
  }
  if (show("runtimes") && inv.runtimes) {
    lines.push("### Runtimes (" + Object.keys(inv.runtimes).length + ")");
    Object.entries(inv.runtimes).sort().forEach(([k,v]) => lines.push(`  ${k.padEnd(12)} ${v}`));
    lines.push("");
  }
  if (show("package_managers") && inv.package_managers) {
    lines.push("### Package managers (" + Object.keys(inv.package_managers).length + ")");
    Object.entries(inv.package_managers).sort().forEach(([k,v]) => lines.push(`  ${k.padEnd(12)} ${v}`));
    lines.push("");
  }
  if (show("browsers") && inv.browsers) {
    lines.push("### Browsers");
    Object.entries(inv.browsers).sort().forEach(([k,v]) => lines.push(`  ${k.padEnd(22)} ${v}`));
    lines.push("");
  }
  if (show("displays") && inv.displays) {
    lines.push("### Displays / GUI");
    Object.entries(inv.displays).forEach(([k,v]) => {
      if (k === "screens") {
        (v||[]).forEach(s => lines.push(`  screen: ${JSON.stringify(s)}`));
      } else {
        lines.push(`  ${k.padEnd(22)} ${v}`);
      }
    });
    lines.push("");
  }
  if (show("services") && inv.services) {
    lines.push("### Services");
    Object.entries(inv.services).forEach(([k,v]) => {
      if (Array.isArray(v)) {
        lines.push(`  ${k} (${v.length}):`);
        v.slice(0, 10).forEach(item => lines.push(`    - ${item}`));
        if (v.length > 10) lines.push(`    ... and ${v.length-10} more`);
      } else {
        lines.push(`  ${k}: ${v}`);
      }
    });
    lines.push("");
  }
  if (show("python_env") && inv.python_env) {
    const pe = inv.python_env;
    lines.push("### Python environment");
    lines.push(`  exe: ${pe.executable}`);
    lines.push(`  version: ${pe.version} (${pe.implementation})  in_venv: ${pe.is_venv}`);
    if (pe.installed_pkgs_count != null) lines.push(`  installed: ${pe.installed_pkgs_count} packages`);
    if (pe.installed_pkgs_top20) {
      lines.push("  top 20:");
      pe.installed_pkgs_top20.forEach(p => lines.push(`    ${p}`));
    }
    lines.push("");
  }
  if (show("env") && inv.env) {
    lines.push("### Env (selected)");
    Object.entries(inv.env).sort().forEach(([k,v]) => {
      if (k === "PATH" || k === "PATH_dirs") return;
      let val = v;
      if (typeof v === "string" && v.length > 120) val = v.slice(0,120)+"…";
      lines.push(`  ${k.padEnd(22)} ${val}`);
    });
    if (inv.env.PATH_entries) {
      lines.push(`  PATH                   (${inv.env.PATH_entries} entries; expand with 'env' section JSON)`);
    }
    lines.push("");
  }

  return lines.join("\n");
}

