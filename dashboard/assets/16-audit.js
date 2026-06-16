// ===== AUDIT =====
async function loadAudit() {
  const n = document.getElementById("auditLines").value || "50";
  const filter = document.getElementById("auditFilter").value;
  const tbody = document.getElementById("auditTable");
  try {
    let path = "/v1/audit?lines=" + n;
    if (filter) path += "&type=" + encodeURIComponent(filter);
    const result = await api(path);
    if (!result.ok) { tbody.innerHTML = "<tr><td colspan='3'>Error: " + esc(result.error||"?") + "</td></tr>"; return; }
    const events = result.events || [];
    if (!events.length) { tbody.innerHTML = "<tr><td colspan='3'>No audit events</td></tr>"; return; }
    tbody.innerHTML = "";
    events.forEach(e => {
      const tr = document.createElement("tr");
      const ts = e.ts || e.timestamp || "?";
      const type = e.type || "?";
      const detail = e.cmd ? ("cmd: " + e.cmd.slice(0,80)) : (e.reason || e.exit_code || "");
      const tdTime = document.createElement("td");
      tdTime.className = "mono";
      tdTime.textContent = String(ts).slice(0,19);
      const tdType = document.createElement("td");
      tdType.textContent = type;
      const tdDetail = document.createElement("td");
      tdDetail.className = "mono";
      tdDetail.style.cssText = "max-width:400px;overflow:hidden;text-overflow:ellipsis";
      tdDetail.textContent = String(detail).slice(0,120);
      tr.appendChild(tdTime); tr.appendChild(tdType); tr.appendChild(tdDetail);
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = "<tr><td colspan='3'>Error loading audit: " + esc(e.message||"Unknown") + "</td></tr>";
  }
}

async function auditStats() {
  const panel = document.getElementById("auditStatsPanel");
  panel.style.display = "block";
  panel.innerHTML = "<span class='spinner'></span> Computing audit statistics...";
  try {
    const result = await api("/v1/audit?lines=1000");
    if (!result.ok) { panel.innerHTML = "Error: " + esc(result.error||"?"); return; }
    const events = result.events || [];
    const typeCounts = {};
    let minTs = null, maxTs = null;
    events.forEach(e => {
      const t = e.type || "unknown";
      typeCounts[t] = (typeCounts[t]||0) + 1;
      const ts = e.ts || e.timestamp;
      if (ts) {
        const d = new Date(ts);
        if (!minTs || d < minTs) minTs = d;
        if (!maxTs || d > maxTs) maxTs = d;
      }
    });

    panel.innerHTML = "";
    const h3 = document.createElement("h3");
    h3.textContent = "Audit Statistics";
    panel.appendChild(h3);

    const statsGrid = document.createElement("div");
    statsGrid.className = "card-grid-sm";
    const totalCard = document.createElement("div");
    totalCard.className = "card";
    totalCard.innerHTML = "<div class='stat info'>" + events.length + "</div><div class='label'>Total Events</div>";
    statsGrid.appendChild(totalCard);
    panel.appendChild(statsGrid);

    // Type counts
    Object.entries(typeCounts).sort((a,b)=>b[1]-a[1]).forEach(([type, count]) => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = "<div class='stat warn'>" + count + "</div><div class='label'>" + esc(type) + "</div>";
      statsGrid.appendChild(card);
    });

    // Time range
    if (minTs && maxTs) {
      const tr = document.createElement("p");
      tr.style.cssText = "font-size:12px;color:var(--text2);margin-top:8px";
      tr.textContent = "Time range: " + minTs.toLocaleString() + " to " + maxTs.toLocaleString();
      panel.appendChild(tr);
    }
  } catch(e) {
    panel.innerHTML = "Error: " + esc(e.message||"Unknown");
  }
}

