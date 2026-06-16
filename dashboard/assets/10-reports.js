// ===== REPORTS =====
async function loadReports() {
  const tbody = document.getElementById("reportsTable");
  try {
    const result = await api("/v1/reports");
    if (!result.ok) { tbody.innerHTML = "<tr><td colspan='4'>Error: " + esc(result.error||"?") + "</td></tr>"; return; }
    if (!result.reports || !result.reports.length) { tbody.innerHTML = "<tr><td colspan='4'>No reports</td></tr>"; return; }
    tbody.innerHTML = "";
    result.reports.forEach(r => {
      const tr = document.createElement("tr");
      const tdName = document.createElement("td");
      tdName.textContent = r.name || "";
      const tdSize = document.createElement("td");
      tdSize.textContent = formatBytes(r.size || 0);
      const tdMod = document.createElement("td");
      tdMod.className = "mono";
      tdMod.textContent = relTime(r.modified);
      const tdActions = document.createElement("td");
      const dlBtn = document.createElement("button");
      dlBtn.className = "info sm";
      dlBtn.textContent = "Download";
      dlBtn.addEventListener("click", () => downloadReport(r.name));
      tdActions.appendChild(dlBtn);
      tr.appendChild(tdName); tr.appendChild(tdSize); tr.appendChild(tdMod); tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = "<tr><td colspan='4'>Error loading reports: " + esc(e.message||"Unknown") + "</td></tr>";
  }
}

function downloadReport(name) {
  const a = document.createElement("a");
  a.href = BASE + "/v1/reports/" + encodeURIComponent(name);
  a.download = name;
  a.click();
}

