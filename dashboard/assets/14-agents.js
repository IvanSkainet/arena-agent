// ===== AGENTS =====
async function loadAgents() {
  const tbody = document.getElementById("agentsTable");
  try {
    const result = await api("/v1/agents");
    if (!result.ok) { tbody.innerHTML = "<tr><td colspan='4'>Error: " + esc(result.error||"?") + "</td></tr>"; return; }
    const agents = result.agents || [];
    if (!agents.length) { tbody.innerHTML = "<tr><td colspan='4'>No agents configured</td></tr>"; return; }
    tbody.innerHTML = "";
    agents.forEach(a => {
      const tr = document.createElement("tr");
      const tdName = document.createElement("td");
      tdName.textContent = a.name || a.id || "?";
      tdName.style.cursor = "pointer";
      tdName.style.color = "var(--blue)";
      tdName.addEventListener("click", () => showAgentDetail(a));
      const tdType = document.createElement("td");
      tdType.textContent = a.type || a.model || "?";
      const tdStatus = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = "badge " + (a.active || a.status === "active" ? "ok" : "gray");
      badge.textContent = a.status || (a.active ? "active" : "inactive");
      tdStatus.appendChild(badge);
      const tdActions = document.createElement("td");
      tr.appendChild(tdName); tr.appendChild(tdType); tr.appendChild(tdStatus); tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = "<tr><td colspan='4'>Error loading agents: " + esc(e.message||"Unknown") + "</td></tr>";
  }
}

function showAgentDetail(agent) {
  const panel = document.getElementById("agentDetail");
  panel.className = "detail-panel open";
  panel.innerHTML = "";
  const h3 = document.createElement("h3");
  h3.textContent = agent.name || agent.id || "Agent";
  panel.appendChild(h3);
  const pre = document.createElement("pre");
  pre.className = "mono";
  pre.style.cssText = "white-space:pre-wrap;margin-top:8px";
  pre.textContent = JSON.stringify(agent, null, 2);
  panel.appendChild(pre);
}

