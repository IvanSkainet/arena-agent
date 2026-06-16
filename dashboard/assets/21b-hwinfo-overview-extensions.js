async function refreshHwinfo() {
  const card = document.getElementById("hwDetails");
  const src = document.getElementById("hwSource");
  if (!card) return;
  card.textContent = "Loading hardware data...";
  if (src) src.textContent = "loading...";

  let hw = null;
  let source = "";

  // Try the unified hardware API first (v2.11.0+), then the legacy alias.
  for (const endpoint of ["/v1/hardware?include_inventory=0", "/v1/hwinfo?include_inventory=0"]) {
    try {
      const r = await api(endpoint);
      if (r && r.ok && (r.hardware || r.hwinfo)) {
        hw = r.hardware || r.hwinfo;
        source = endpoint.split("?")[0] + " (bridge)";
        break;
      }
    } catch (e) {}
  }

  // Fallback to /v1/sysinfo
  if (!hw) {
    try {
      const r = await api("/v1/sysinfo");
      if (r && r.ok) {
        hw = {
          os: { system: "?", release: "?", machine: "?" },
          cpu: { name: "CPU", cores: r.cpu_cores, threads: r.cpu_threads, max_ghz: 0 },
          ram_total_gb: (r.mem_total_mb / 1024).toFixed(1),
          ram_avail_gb: (r.mem_avail_mb / 1024).toFixed(1),
          disks: [{ device: "/", total_gb: r.disk_total_gb, free_gb: r.disk_free_gb,
                    used_pct: r.disk_total_gb ? ((r.disk_total_gb - r.disk_free_gb) / r.disk_total_gb * 100).toFixed(1) : 0,
                    filesystem: "" }],
        };
        source = "/v1/sysinfo (fallback, basic)";
      }
    } catch (e) {}
  }

  if (!hw) {
    card.textContent = "Hardware info unavailable";
    if (src) { src.textContent = "error"; src.className = "badge red"; }
    return;
  }

  if (src) {
    src.textContent = source;
    src.className = "badge " + (source.includes("hardware") || source.includes("hwinfo") ? "green" : "warn");
  }

  // Format
  const lines = [];
  const os = hw.os || {};
  lines.push(`OS:      ${os.system || "?"} ${os.release || ""} (${os.machine || ""}, host: ${os.node || "?"})`);

  if (hw.motherboard) {
    const m = hw.motherboard;
    lines.push(`Board:   ${m.manufacturer || "?"} ${m.product || ""} ${m.version ? "(rev " + m.version + ")" : ""}`);
  }
  if (hw.bios) {
    const b = hw.bios;
    let date = b.release_date || "";
    if (/^\d{8}/.test(date)) date = `${date.substring(0,4)}-${date.substring(4,6)}-${date.substring(6,8)}`;
    lines.push(`BIOS:    ${b.manufacturer || ""} v${b.version || ""} ${date ? "(" + date + ")" : ""}`);
  }
  if (hw.cpu) {
    const c = hw.cpu;
    lines.push(`CPU:     ${c.name || "?"} (${c.cores || "?"} cores / ${c.threads || "?"} threads${c.max_ghz ? ", " + c.max_ghz + " GHz" : ""})`);
  }
  if (hw.gpus && hw.gpus.length) {
    hw.gpus.forEach((g, i) => {
      lines.push(`GPU${i > 0 ? (i+1) : ":"}    ${g.name}${g.vram_mb ? " (" + (g.vram_mb / 1024).toFixed(1) + " GB VRAM)" : ""}`);
    });
  } else if (hw.gpu) {
    lines.push(`GPU:     ${hw.gpu.name}${hw.gpu.vram_mb ? " (" + (hw.gpu.vram_mb / 1024).toFixed(1) + " GB VRAM)" : ""}`);
  }

  if (hw.ram_total_gb) {
    const used = hw.ram_used_gb;
    const avail = hw.ram_avail_gb;
    let line = `RAM:     ${hw.ram_total_gb} GB total`;
    if (used != null) line += `, ${used} GB used`;
    if (avail != null) line += `, ${avail} GB free`;
    lines.push(line);
  }
  if (hw.ram_modules && hw.ram_modules.length) {
    hw.ram_modules.forEach((m, i) => {
      lines.push(`         Slot ${i+1}: ${m.size_gb} GB${m.speed_mhz ? " @ " + m.speed_mhz + " MHz" : ""}${m.manufacturer ? " — " + m.manufacturer : ""}${m.part_number ? " (" + m.part_number + ")" : ""}`);
    });
  }

  if (hw.disks && hw.disks.length) {
    lines.push(``);
    lines.push(`Disks:`);
    hw.disks.forEach(d => {
      lines.push(`  ${d.device} ${d.volume ? "(" + d.volume + ")" : ""} — ${d.free_gb} GB free of ${d.total_gb} GB ${d.filesystem ? "[" + d.filesystem + "]" : ""} (${d.used_pct}% used)`);
    });
  }

  card.textContent = lines.join("\n");
}

// Hook into existing refreshOverview if present
const _origRefreshOverview = typeof refreshOverview === "function" ? refreshOverview : null;
window.refreshOverview = async function() {
  if (_origRefreshOverview) {
    try { await _origRefreshOverview(); } catch (e) {}
  }
  // Run hwinfo in background — don't await to prevent blocking the overview refresh
  refreshHwinfo().catch(() => {});
};

// Hook expandSlash into runCommand if present
const _origRunCommand = typeof runCommand === "function" ? runCommand : null;
window.runCommand = async function(cmd) {
  const inp = document.getElementById("termCmd");
  if (inp && !cmd) {
    const expanded = expandSlash(inp.value);
    if (expanded !== inp.value) inp.value = expanded;
  }
  if (_origRunCommand) return _origRunCommand(cmd);
};

// Initialize on DOM ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => { setupSlashSuggest(); refreshHwinfo(); });
} else {
  setupSlashSuggest();
  refreshHwinfo();
}


