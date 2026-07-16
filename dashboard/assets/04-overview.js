// ===== OVERVIEW =====
async function refreshOverview() {
  try {
    const health = await api("/health");
    const status = await api("/v1/status");
    const sysinfo = await api("/v1/sysinfo");
    const mem = await api("/v1/memory");
    const missions = await api("/v1/missions");
    const tasks = await api("/v1/tasks");

    if (health.ok !== undefined && health.ok !== false) {
      document.getElementById("pingDot").className = "ping ok";
      document.getElementById("pingText").textContent = "Connected";
      document.getElementById("statVersion").textContent = health.version ? "v" + health.version : "--";
      document.getElementById("statHost").textContent = health.host || sysinfo.hostname || "--";
      document.getElementById("sidebarVersion").textContent = health.version || "--";
      document.getElementById("versionTag").textContent = "v" + (health.version || "--");

      // Uptime
      if (health.uptime_seconds !== undefined) {
        document.getElementById("statUptime").textContent = formatUptime(health.uptime_seconds);
      }

      // Handle reconnection
      if (wasOffline) {
        wasOffline = false;
        lastConnectedTime = new Date();
        const reconnectMsg = document.getElementById("reconnectMsg");
        reconnectMsg.textContent = "Reconnected at " + lastConnectedTime.toLocaleTimeString();
        reconnectMsg.style.display = "block";
        setTimeout(() => { reconnectMsg.style.display = "none"; }, 5000);
      }
      lastConnectedTime = new Date();
    } else {
      document.getElementById("pingDot").className = "ping err";
      document.getElementById("pingText").textContent = "Offline";
      wasOffline = true;
      const reconnectMsg = document.getElementById("reconnectMsg");
      reconnectMsg.textContent = "Connection lost. Reconnecting...";
      reconnectMsg.style.display = "block";
      document.getElementById("pingDot").className = "ping reconnecting";
    }

    if (status.ok) {
      document.getElementById("statProfile").textContent = status.profile || "--";
      if (status.metrics) {
        overviewMetrics.requests = status.metrics.total_requests || overviewMetrics.requests;
        overviewMetrics.execs = status.metrics.exec_count || overviewMetrics.execs;
      }
      // Network Status — provider-agnostic. Reads /v1/tunnels/status which
      // covers Tailscale, Cloudflared, and ZeroTier as one pool with
      // automatic failover, and reports whichever provider is currently
      // giving clients a reachable URL. Never assume it will be Tailscale.
      try {
        const tun = await api("/v1/tunnels/status");
        const activeBadge = document.getElementById("netActiveProvider");
        const urlEl = document.getElementById("netActiveUrl");
        const listEl = document.getElementById("netProvidersList");
        if (tun && tun.ok) {
          const active = tun.active || null;
          if (activeBadge) {
            if (active && active.provider) {
              activeBadge.className = "badge ok";
              activeBadge.textContent = active.provider;
            } else {
              activeBadge.className = "badge fail";
              activeBadge.textContent = "none";
            }
          }
          if (urlEl) {
            // v4.1.1: show ALL reachable provider URLs (not just the
            // primary), each with a Copy button. Agents on the same
            // ZeroTier or Tailscale network can pick whichever URL
            // routes for them without pasting the wrong one.
            urlEl.innerHTML = "";
            const reachable = (tun.providers || []).filter(p => p.active && p.public_url);
            if (reachable.length === 0) {
              urlEl.textContent = "—";
            } else {
              reachable.forEach((p, idx) => {
                if (idx) urlEl.appendChild(document.createTextNode("   "));
                const label = document.createElement("span");
                label.style.color = "var(--text2)";
                label.style.fontSize = "11px";
                label.textContent = p.provider + ":";
                urlEl.appendChild(label);
                urlEl.appendChild(document.createTextNode(" "));
                const a = document.createElement("a");
                a.href = p.public_url;
                a.target = "_blank";
                a.rel = "noreferrer";
                a.textContent = p.public_url;
                urlEl.appendChild(a);
                urlEl.appendChild(document.createTextNode(" "));
                const btn = document.createElement("button");
                btn.className = "sm";
                btn.style.fontSize = "11px";
                btn.style.padding = "1px 6px";
                btn.textContent = "Copy";
                btn.onclick = (ev) => {
                  ev.preventDefault();
                  if (navigator.clipboard) navigator.clipboard.writeText(p.public_url);
                  btn.textContent = "✓";
                  setTimeout(() => { btn.textContent = "Copy"; }, 1200);
                };
                urlEl.appendChild(btn);
              });
            }
          }
          if (listEl) {
            const parts = (tun.providers || []).map((p) => {
              let mark = "·";
              if (p.active) mark = "✓";
              else if (p.installed) mark = "○";
              else mark = "✗";
              return mark + " " + p.provider;
            });
            listEl.textContent = parts.length ? parts.join("   ") : "—";
          }
        } else {
          if (activeBadge) { activeBadge.className = "badge gray"; activeBadge.textContent = "Unknown"; }
          if (urlEl) urlEl.textContent = "—";
          if (listEl) listEl.textContent = "—";
        }
      } catch (e) { /* ignore */ }
    }

    if (sysinfo.ok) {
      document.getElementById("statCPU").textContent = sysinfo.cpu_threads || "--";
      const memTotalGB = (sysinfo.mem_total_mb / 1024).toFixed(1);
      document.getElementById("statRAM").textContent = memTotalGB + " GB";
      document.getElementById("statDisk").textContent = sysinfo.disk_free_gb + " GB";

      // CPU usage
      if (sysinfo.cpu_percent !== undefined) setBar("cpuBar", sysinfo.cpu_percent, "green");
      // RAM usage
      if (sysinfo.mem_avail_mb !== undefined && sysinfo.mem_total_mb) {
        const usedPct = ((sysinfo.mem_total_mb - sysinfo.mem_avail_mb) / sysinfo.mem_total_mb) * 100;
        setBar("ramBar", usedPct, "blue");
      }
      // Disk usage
      if (sysinfo.disk_total_gb !== undefined && sysinfo.disk_free_gb !== undefined) {
        const diskUsedPct = ((sysinfo.disk_total_gb - sysinfo.disk_free_gb) / sysinfo.disk_total_gb) * 100;
        setBar("diskBar", diskUsedPct, "purple");
      }
      // Load average (Linux only)
      if (sysinfo.load_average) {
        document.getElementById("loadAvgRow").style.display = "flex";
        const la = sysinfo.load_average;
        document.getElementById("loadAvgText").textContent = la[0].toFixed(2) + " / " + la[1].toFixed(2) + " / " + la[2].toFixed(2);
      }
      // Platform info
      if (sysinfo.python_version) document.getElementById("platPython").textContent = sysinfo.python_version;
      if (sysinfo.os_build) document.getElementById("platOS").textContent = sysinfo.os_build;
      if (sysinfo.platform) document.getElementById("platArch").textContent = sysinfo.platform;

      // Sysinfo card - XSS safe

    }

    if (mem.ok) document.getElementById("statMemory").textContent = mem.count;
    if (missions.ok) document.getElementById("statMissions").textContent = missions.count;

    // Active tasks count
    if (tasks.ok && tasks.tasks) {
      const active = tasks.tasks.filter(t => t.state === "running" || t.state === "inbox").length;
      document.getElementById("statActiveTasks").textContent = active;
    }

    // Update bridge metrics display
    document.getElementById("metricReqs").textContent = overviewMetrics.requests;
    document.getElementById("metricExecs").textContent = overviewMetrics.execs;
    document.getElementById("metricErrors").textContent = overviewMetrics.errors;

    // Refresh control overview card
    refreshControlPanel();

  } catch(e) {
    document.getElementById("pingDot").className = "ping err";
    document.getElementById("pingText").textContent = "Error";
    wasOffline = true;
    const reconnectMsg = document.getElementById("reconnectMsg");
    reconnectMsg.textContent = "Connection error. Retrying...";
    reconnectMsg.style.display = "block";
    document.getElementById("pingDot").className = "ping reconnecting";
  }
}

