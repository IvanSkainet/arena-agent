// ===== SETTINGS =====
async function refreshSettings() {
  // Service mode badge
  try {
    const si = await api("/v1/service/info");
    const el = document.getElementById("setServiceMode");
    if (el && si && si.ok) {
      const mode = si.running_as || "unknown";
      const labels = {
        "nssm-service":   ["NSSM Windows Service", "ok"],
        "scheduled-task": ["Windows Scheduled Task", "warn"],
        "systemd-user":   ["systemd-user (Linux)", "ok"],
        "launchd":        ["launchd (macOS)", "ok"],
        "unknown":        ["Manual / unmanaged", "warn"],
      };
      const [label, kind] = labels[mode] || [mode, "gray"];
      el.className = "badge " + kind;
      el.textContent = label + (si.pid ? "  (PID " + si.pid + ")" : "");
      el.title = JSON.stringify(si, null, 2);
    }
  } catch (e) { /* ignore */ }

  try {
    const health = await api("/health");
    if (health.ok !== undefined && health.uptime_seconds !== undefined) {
      document.getElementById("setUptime").textContent = formatUptime(health.uptime_seconds);
    }
    // Env info
    const sysinfo = await api("/v1/sysinfo");
    if (sysinfo.ok) {
      const envParts = [];
      if (sysinfo.python_version) envParts.push("Python: " + sysinfo.python_version);
      if (sysinfo.platform) envParts.push("Platform: " + sysinfo.platform);
      if (sysinfo.os_build) envParts.push("OS: " + sysinfo.os_build);
      if (sysinfo.cpu_threads) envParts.push("CPU Threads: " + sysinfo.cpu_threads);
      if (sysinfo.mem_total_mb) envParts.push("RAM: " + (sysinfo.mem_total_mb/1024).toFixed(1) + " GB");
      if (sysinfo.disk_free_gb) envParts.push("Disk Free: " + sysinfo.disk_free_gb + " GB");
      if (sysinfo.architecture) envParts.push("Arch: " + sysinfo.architecture);
      document.getElementById("envInfo").textContent = envParts.join("\n");
    }
    // Metrics
    document.getElementById("setRequests").textContent = overviewMetrics.requests;
    document.getElementById("setErrors").textContent = overviewMetrics.errors;
    // Tunnel status per-transport now lives on the Transports tab; this
    // block used to query /v1/tailscale/funnel/status and
    // /v1/cloudflared/tunnel/status to paint tsToggleStatus / cfToggleStatus
    // badges, but the Settings card was reduced to a "Go to Transports tab"
    // link so those DOM ids no longer exist. See dashboard/assets/20-transports.js.
    // Webhooks
    const wh = await api("/v1/webhooks");
    if (wh && wh.ok && wh.webhooks) {
      document.getElementById("setWebhookUrls").value = (wh.webhooks.urls || []).join("\n");
      document.getElementById("setWebhookEvents").value = (wh.webhooks.events || []).join(", ");
    }
  } catch(e) {
    // Silent fail
  }
}

async function saveWebhooks() {
  const urlsRaw = document.getElementById("setWebhookUrls").value;
  const eventsRaw = document.getElementById("setWebhookEvents").value;
  
  const urls = urlsRaw.split("\n").map(s => s.trim()).filter(s => s.startsWith("http"));
  const events = eventsRaw.split(",").map(s => s.trim()).filter(s => s.length > 0);
  
  if (events.length === 0) events.push("*");
  
  try {
    const res = await api("/v1/webhooks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls, events })
    });
    if (res.ok) {
      alert("Webhooks saved successfully.");
      refreshSettings();
    } else {
      alert("Error saving webhooks: " + res.error);
    }
  } catch (e) {
    alert("Error: " + e.message);
  }
}

// _humanTunnelError removed along with the tsFunnelToggle / cfFunnelToggle
// callers that were its only consumers. The Transports tab surfaces its own
// per-transport hint text via the tr-hint slot in each card.

// tsFunnelToggle / cfFunnelToggle removed in the Settings-migration cleanup.
// Their functionality now lives on the Transports tab as transportStart('tailscale') /
// transportStart('cloudflared') in dashboard/assets/20-transports.js.
// If a bookmarked script still calls the old names it will get a ReferenceError;
// operators should open the Transports tab and use the per-transport Start/Stop
// buttons there. Removed here rather than shimmed because keeping named
// stubs would silently pretend to work and hide the migration from users.
