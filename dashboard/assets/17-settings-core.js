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

async function bridgeRestart() {
  if (!confirm("Restart the bridge?\n\nThe page will temporarily lose connection " +
               "and reload once the bridge is back up.")) return;
  try {
    // Capture the restart response (it tells us if respawn helper was spawned)
    const restartPromise = api("/v1/restart", {method: "POST"}).catch(e => ({ok:false, error: e.message||String(e)}));

    // Poll /health until back
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.65);z-index:9999;" +
      "display:flex;align-items:center;justify-content:center;font-family:var(--mono);color:#fff;font-size:14px";
    overlay.innerHTML = "<div id='restartBox' style='background:#222;padding:20px 32px;border-radius:8px;max-width:560px;text-align:center'>" +
      "<div><span class='spinner'></span> Restarting bridge... (page will reload when ready)</div>" +
      "<div id='restartMeta' style='margin-top:8px;color:#888;font-size:11px'></div>" +
      "</div>";
    document.body.appendChild(overlay);

    // Show what /v1/restart returned (respawn method, etc)
    restartPromise.then(r => {
      const meta = document.getElementById("restartMeta");
      if (!meta) return;
      if (r && r.ok) {
        if (r.respawn_scheduled === false) {
          meta.style.color = "#f87171";
          meta.textContent = "⚠ Respawn helper failed: " + (r.method || "?") +
                             ". You may need to start the bridge manually.";
        } else if (r.method) {
          meta.textContent = "Respawn method: " + r.method;
        }
      } else if (r && r.error) {
        meta.style.color = "#f87171";
        meta.textContent = "Restart endpoint error: " + r.error;
      }
    });

    let tries = 0;
    const max = 45;  // 45 sec to allow scheduled-task respawn
    const interval = setInterval(async () => {
      tries++;
      const box = document.getElementById("restartBox");
      if (box) {
        const spin = box.querySelector(".spinner");
        if (spin && tries > 1) {
          // Append elapsed time once per second
          let counter = box.querySelector("#restartElapsed");
          if (!counter) {
            counter = document.createElement("span");
            counter.id = "restartElapsed";
            counter.style.cssText = "margin-left:8px;color:#888";
            spin.after(counter);
          }
          counter.textContent = "(" + tries + "s)";
        }
      }
      try {
        const r = await fetch(BASE + "/health", {cache: "no-store"});
        if (r.ok) {
          clearInterval(interval);
          // tiny delay so user sees the success message
          const m = document.getElementById("restartMeta");
          if (m) { m.style.color = "#4ade80"; m.textContent = "✓ Bridge is back. Reloading..."; }
          setTimeout(() => location.reload(), 500);
        }
      } catch (_) { /* keep polling */ }
      if (tries >= max) {
        clearInterval(interval);
        const box2 = document.getElementById("restartBox");
        if (box2) {
          box2.innerHTML =
            "<div style='color:#f87171;font-weight:600;margin-bottom:8px'>Bridge did not come back after " + max + "s</div>" +
            "<div style='font-size:11px;color:#aaa;margin-bottom:8px'>Try manually in PowerShell:</div>" +
            "<pre style='background:#111;padding:8px;font-size:11px;text-align:left;border-radius:4px'>" +
            "schtasks /Run /tn ArenaUnifiedBridge\n" +
            "Start-Sleep 4\n" +
            "curl -UseBasicParsing http://127.0.0.1:" + (location.port||8765) + "/health</pre>" +
            "<button onclick='location.reload()' style='margin-top:8px'>Reload anyway</button> " +
            "<button onclick='this.closest(\"div[style*=fixed]\").remove()'>Cancel</button>";
        }
      }
    }, 1000);
  } catch(e) {
    alert("Error restarting bridge: " + (e.message||"Unknown error"));
  }
}

