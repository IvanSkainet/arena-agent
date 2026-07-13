// ===== DOCTOR =====
async function runDoctor() {
  const doctorEl = document.getElementById("doctorResults");
  doctorEl.innerHTML = "<span class='spinner'></span> Running diagnostics...";
  // Load service status
  const svcEl = document.getElementById("serviceStatus");
  svcEl.innerHTML = "<span class='spinner'></span>";
  const tsEl = document.getElementById("doctorTailscale");
  if (tsEl) tsEl.innerHTML = "<span class='spinner'></span>";
  const raEl = document.getElementById("doctorRemoteAccess");
  if (raEl) raEl.innerHTML = "<span class='spinner'></span>";

  try {
    const result = await api("/v1/doctor");
    if (!result.ok) {
      doctorEl.innerHTML = "<div class='card'>Error: " + esc(result.error||"?") + "</div>";
      svcEl.textContent = "Error loading status";
      tsEl.textContent = "Error loading status";
      return;
    }
    const passed = result.passed;
    const total = result.total;

    // Service status — fetch /v1/sys/svc directly (v1.6.4)
    try {
      const svc = await api("/v1/sys/svc");
      if (svc && svc.ok) {
        svcEl.innerHTML = "";
        const items = [];
        // Windows: only show the active service method
        if (svc.windows_service) {
          const nssmRunning = svc.windows_service.running;
          const nssmDetail = svc.windows_service.detail || "";
          // If NSSM is not registered, skip it (user uses Scheduled Task instead)
          if (nssmDetail.includes("not registered")) {
            // Don't show — no NSSM installed
          } else {
            items.push(["NSSM/Windows Service", nssmRunning, nssmDetail]);
          }
        }
        if (svc.scheduled_task) {
          // Skip showing Scheduled Task if NSSM is running (redundant)
          const nssmRunning = svc.windows_service && svc.windows_service.running;
          if (!nssmRunning) {
            items.push(["Scheduled Task", svc.scheduled_task.running, svc.scheduled_task.detail || ""]);
          }
        }
        if (svc.systemd_user) {
          items.push(["systemd Service", svc.systemd_user.active, svc.systemd_user.detail || ""]);
        }
        if (svc.launchd) {
          items.push(["launchd Service", svc.launchd.active, svc.launchd.detail || ""]);
        }
        if (svc.bridge_processes) {
          items.push(["Bridge processes", svc.bridge_processes.count > 0,
                      "count: " + svc.bridge_processes.count]);
        }
        if (svc.tailscale) {
          items.push(["Tailscale", svc.tailscale.connected, svc.tailscale.error || "connected"]);
        }
        // Also surface Cloudflared + ZeroTier so Doctor covers every
        // remote-access provider, not just Tailscale. These fields may
        // be absent on older bridges — hence the `if (svc.xxx)` guards.
        if (svc.cloudflared) {
          items.push(["Cloudflared",
                      !!svc.cloudflared.installed,
                      svc.cloudflared.error || (svc.cloudflared.active ? "tunnel active" : (svc.cloudflared.installed ? "installed, tunnel idle" : "not installed"))]);
        }
        if (svc.zerotier) {
          items.push(["ZeroTier",
                      !!(svc.zerotier.installed || svc.zerotier.connected),
                      svc.zerotier.error || (svc.zerotier.connected ? ("node " + (svc.zerotier.node_id || "?")) : (svc.zerotier.installed ? "installed" : "not installed"))]);
        }
        items.forEach(([name, ok, detail]) => {
          const div = document.createElement("div");
          div.className = "row";
          div.style.cssText = "align-items:flex-start;gap:8px;margin-bottom:4px";
          const badge = document.createElement("span");
          badge.className = "badge " + (ok ? "ok" : "fail");
          badge.textContent = ok ? "OK" : "DOWN";
          const nameSpan = document.createElement("span");
          nameSpan.style.cssText = "font-size:12px;font-weight:600;min-width:160px";
          nameSpan.textContent = name;
          const detEl = document.createElement("span");
          detEl.style.cssText = "font-size:11px;color:var(--text2);font-family:var(--mono);white-space:pre-wrap;flex:1";
          detEl.textContent = (detail || "").toString().slice(0, 300);
          div.appendChild(badge); div.appendChild(nameSpan); div.appendChild(detEl);
          svcEl.appendChild(div);
        });
      } else {
        svcEl.textContent = "Service info not available (svc.ok=false)";
      }
    } catch (e) {
      svcEl.textContent = "Service info error: " + (e.message || e);
    }

    // Remote access — provider-agnostic. Shows every configured tunnel
    // provider (Tailscale, Cloudflared, ZeroTier) with its installed /
    // connected / active state, and highlights whichever one is currently
    // giving clients a reachable URL. Never assumes Tailscale.
    const target = raEl || tsEl;
    if (target) {
      try {
        const tun = await api("/v1/tunnels/status");
        target.innerHTML = "";
        if (!tun || !tun.ok) {
          target.textContent = "Remote-access info not available";
        } else {
          const wrap = document.createElement("div");
          wrap.style.cssText = "display:flex;flex-direction:column;gap:8px";

          // Active endpoint row.
          const activeRow = document.createElement("div");
          activeRow.className = "row";
          const ab = document.createElement("span");
          if (tun.active && tun.active.provider) {
            ab.className = "badge ok";
            ab.textContent = "Active: " + tun.active.provider;
          } else {
            ab.className = "badge fail";
            ab.textContent = "No active tunnel";
          }
          activeRow.appendChild(ab);
          if (tun.active?.public_url) {
            const u = document.createElement("a");
            u.href = tun.active.public_url;
            u.target = "_blank";
            u.className = "mono";
            u.style.cssText = "font-size:12px;margin-left:8px";
            u.textContent = tun.active.public_url;
            activeRow.appendChild(u);
          }
          wrap.appendChild(activeRow);

          // Per-provider rows.
          for (const p of (tun.providers || [])) {
            const row = document.createElement("div");
            row.className = "row";
            row.style.cssText = "gap:6px";

            const nameLbl = document.createElement("span");
            nameLbl.style.cssText = "font-size:12px;font-weight:600;width:100px";
            nameLbl.textContent = p.provider;
            row.appendChild(nameLbl);

            const state = document.createElement("span");
            let label = "off";
            let cls = "gray";
            if (!p.installed) { label = "not installed"; cls = "gray"; }
            else if (p.active) { label = "active"; cls = "ok"; }
            else if (p.connected) { label = "connected"; cls = "warn"; }
            else { label = "installed"; cls = "gray"; }
            state.className = "badge " + cls;
            state.textContent = label;
            row.appendChild(state);

            if (p.public_url) {
              const u = document.createElement("a");
              u.href = p.public_url; u.target = "_blank";
              u.className = "mono";
              u.style.cssText = "font-size:11px;margin-left:6px";
              u.textContent = p.public_url;
              row.appendChild(u);
            }
            wrap.appendChild(row);
          }

          target.appendChild(wrap);
        }
      } catch (e) {
        target.textContent = "Remote-access info error: " + (e.message || e);
      }
    }

    // Doctor results
    doctorEl.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    const statDiv = document.createElement("div");
    statDiv.className = "stat " + (passed===total?"":"warn");
    statDiv.textContent = passed + "/" + total;
    card.appendChild(statDiv);
    const labelDiv = document.createElement("div");
    labelDiv.className = "label";
    labelDiv.textContent = "Checks Passed";
    card.appendChild(labelDiv);
    doctorEl.appendChild(card);

    (result.checks || []).forEach(c => {
      const checkCard = document.createElement("div");
      checkCard.className = "card";
      checkCard.style.padding = "8px 16px";
      const badge = document.createElement("span");
      badge.className = "badge " + (c.ok ? "ok" : "fail");
      badge.textContent = c.ok ? "PASS" : "FAIL";
      checkCard.appendChild(badge);
      checkCard.appendChild(document.createTextNode(" "));
      const strong = document.createElement("strong");
      strong.textContent = c.name || "";
      checkCard.appendChild(strong);
      checkCard.appendChild(document.createTextNode(" "));
      const span = document.createElement("span");
      span.style.cssText = "color:var(--text2);font-size:12px";
      span.textContent = c.detail || "";
      checkCard.appendChild(span);
      doctorEl.appendChild(checkCard);
    });
  } catch(e) {
    doctorEl.innerHTML = "<div class='card'>Diagnostics error: " + esc(e.message||"Unknown") + "</div>";
    svcEl.textContent = "Error";
    tsEl.textContent = "Error";
  }
}

