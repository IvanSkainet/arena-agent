// ===== DOCTOR =====
async function runDoctor() {
  const doctorEl = document.getElementById("doctorResults");
  doctorEl.innerHTML = "<span class='spinner'></span> Running diagnostics...";
  // Load service status
  const svcEl = document.getElementById("serviceStatus");
  svcEl.innerHTML = "<span class='spinner'></span>";
  const tsEl = document.getElementById("doctorTailscale");
  tsEl.innerHTML = "<span class='spinner'></span>";

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

    // Tailscale Funnel — fetch /v1/sys/funnel directly (v1.6.4)
    try {
      const fn = await api("/v1/sys/funnel");
      if (fn && fn.ok) {
        tsEl.innerHTML = "";
        const wrap = document.createElement("div");
        wrap.style.cssText = "display:flex;flex-direction:column;gap:6px";

        // 1. Funnel active badge
        const row1 = document.createElement("div");
        row1.className = "row";
        const fb = document.createElement("span");
        fb.className = "badge " + (fn.funnel?.active ? "ok" : "fail");
        fb.textContent = fn.funnel?.active ? "Funnel: ACTIVE" : "Funnel: inactive";
        row1.appendChild(fb);
        if (fn.funnel?.url) {
          const u = document.createElement("a");
          u.href = fn.funnel.url; u.target = "_blank";
          u.className = "mono"; u.style.cssText = "font-size:12px;margin-left:8px";
          u.textContent = fn.funnel.url;
          row1.appendChild(u);
        }
        wrap.appendChild(row1);

        // 2. Tailscale connected badge
        const row2 = document.createElement("div");
        row2.className = "row";
        const tb = document.createElement("span");
        tb.className = "badge " + (fn.tailscale?.connected ? "ok" : "fail");
        tb.textContent = fn.tailscale?.connected ? "Tailscale: connected" : "Tailscale: down";
        row2.appendChild(tb);
        wrap.appendChild(row2);

        // 3. Raw status (collapsible)
        if (fn.tailscale?.status || fn.funnel?.status) {
          const det = document.createElement("details");
          det.style.cssText = "margin-top:6px";
          const sum = document.createElement("summary");
          sum.style.cssText = "cursor:pointer;font-size:11px;color:var(--text2)";
          sum.textContent = "Raw output";
          det.appendChild(sum);
          const pre = document.createElement("pre");
          pre.style.cssText = "margin:6px 0 0;font-size:11px;background:var(--bg2);padding:6px;white-space:pre-wrap";
          pre.textContent = (fn.tailscale?.status || "") + "\n\n" + (fn.funnel?.status || "");
          det.appendChild(pre);
          wrap.appendChild(det);
        }
        tsEl.appendChild(wrap);
      } else {
        tsEl.textContent = "Tailscale info not available";
      }
    } catch (e) {
      tsEl.textContent = "Funnel info error: " + (e.message || e);
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

