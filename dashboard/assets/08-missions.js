// ===== MISSIONS =====
async function loadMissions() {
  const tbody = document.getElementById("missionsTable");
  try {
    const result = await api("/v1/missions");
    if (!result.ok) { tbody.innerHTML = "<tr><td colspan='4'>Error: " + esc(result.error||"?") + "</td></tr>"; return; }
    if (!result.missions || !result.missions.length) { tbody.innerHTML = "<tr><td colspan='4'>No missions</td></tr>"; return; }
    tbody.innerHTML = "";
    result.missions.forEach(m => {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + esc(m.name) + "</td><td>" + esc(m.ext) + "</td><td>" + esc(m.size) + "</td><td class='mono'>" + esc(relTime(m.modified)) + "</td>";
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = "<tr><td colspan='4'>Error loading missions: " + esc(e.message||"Unknown") + "</td></tr>";
  }
}

