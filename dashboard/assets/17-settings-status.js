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
    // Tailscale status
    const fn = await api("/v1/tailscale/funnel/status");
    if (fn && fn.ok) {
      const badge = document.getElementById("tsToggleStatus");
      const active = !!fn.active;
      badge.className = "badge " + (active ? "ok" : "fail");
      badge.textContent = active ? "Active" : "Inactive";
    }
    // Cloudflare status
    const cf = await api("/v1/cloudflared/tunnel/status");
    if (cf && cf.ok) {
      const badge = document.getElementById("cfToggleStatus");
      const active = !!cf.active;
      badge.className = "badge " + (active ? "ok" : "fail");
      badge.textContent = active ? "Active" : "Inactive";
      const aUrl = document.getElementById("cfUrl");
      if (active && cf.url) {
        aUrl.href = cf.url;
        aUrl.textContent = cf.url;
        aUrl.style.display = "inline-block";
      } else {
        aUrl.style.display = "none";
      }
    }
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

async function tsFunnelToggle(action) {
  try {
    const result = await api("/v1/tailscale/funnel/" + action, {method: "POST"});
    if (result.ok) {
      refreshOverview();
    } else {
      alert("Error: " + (result.error||"?"));
    }
  } catch(e) {
    alert("Error toggling Tailscale funnel: " + (e.message||"Unknown error"));
  }
}

async function cfFunnelToggle(action) {
  try {
    const result = await api("/v1/cloudflared/tunnel/" + action, {method: "POST"});
    if (result.ok) {
      refreshOverview();
    } else {
      alert("Error: " + (result.error||"?"));
    }
  } catch(e) {
    alert("Error toggling Cloudflare tunnel: " + (e.message||"Unknown error"));
  }
}
