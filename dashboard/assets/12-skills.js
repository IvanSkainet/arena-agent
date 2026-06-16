// ===== SKILLS =====
async function loadSkills() {
  const tbody = document.getElementById("skillsTable");
  try {
    const result = await api("/v1/skills");
    if (!result.ok) { tbody.innerHTML = "<tr><td colspan='3'>Error: " + esc(result.error||"?") + "</td></tr>"; return; }
    const skills = result.skills || [];
    if (!skills.length) { tbody.innerHTML = "<tr><td colspan='3'>No skills available</td></tr>"; return; }
    tbody.innerHTML = "";
    skills.forEach(s => {
      const tr = document.createElement("tr");
      const tdName = document.createElement("td");
      const badge = s.is_third_party ? `<span class="badge warning" style="margin-right:6px;font-size:10px">Plugin</span>` : `<span class="badge ok" style="margin-right:6px;font-size:10px">Core</span>`;
      tdName.innerHTML = badge + esc(s.name || s.id || "?");
      tdName.style.cursor = "pointer";
      tdName.style.color = "var(--blue)";
      tdName.addEventListener("click", () => showSkillDetail(s));
      const tdDesc = document.createElement("td");
      tdDesc.textContent = (s.description || "").slice(0,80);
      tdDesc.style.color = "var(--text2)";
      const tdActions = document.createElement("td");
      const runBtn = document.createElement("button");
      runBtn.className = "success sm";
      runBtn.textContent = "Run";
      runBtn.addEventListener("click", () => runSkill(s));
      tdActions.appendChild(runBtn);
      tr.appendChild(tdName); tr.appendChild(tdDesc); tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = "<tr><td colspan='3'>Error loading skills: " + esc(e.message||"Unknown") + "</td></tr>";
  }
}

function showSkillDetail(skill) {
  const panel = document.getElementById("skillDetail");
  panel.className = "detail-panel open";
  panel.innerHTML = "";
  const h3 = document.createElement("h3");
  h3.textContent = skill.name || skill.id || "Skill";
  panel.appendChild(h3);
  if (skill.description) {
    const p = document.createElement("p");
    p.textContent = skill.description;
    p.style.color = "var(--text2)";
    p.style.marginTop = "4px";
    panel.appendChild(p);
  }
  const pre = document.createElement("pre");
  pre.className = "mono";
  pre.style.cssText = "white-space:pre-wrap;margin-top:8px";
  pre.textContent = JSON.stringify(skill, null, 2);
  panel.appendChild(pre);
  
  if (skill.file && skill.file.includes("third_party")) {
    const rmBtn = document.createElement("button");
    rmBtn.className = "danger sm";
    rmBtn.style.marginTop = "8px";
    rmBtn.textContent = "Uninstall";
    rmBtn.onclick = () => uninstallSkill(skill.name || skill.id);
    panel.appendChild(rmBtn);
  }
}

async function installSkill() {
  const name = document.getElementById("installSkillName").value.trim();
  const url = document.getElementById("installSkillUrl").value.trim();
  if (!name || !url) return alert("Skill name and URL are required.");
  try {
    const res = await api("/v1/skills/install", {method: "POST", body: JSON.stringify({name, url})});
    if (res.ok) {
      alert("Skill installed successfully!");
      document.getElementById("installSkillName").value = "";
      document.getElementById("installSkillUrl").value = "";
      loadSkills();
    } else {
      alert("Install failed: " + res.error);
    }
  } catch(e) {
    alert("Error: " + e.message);
  }
}

async function uninstallSkill(name) {
  if (!confirm(`Are you sure you want to uninstall '${name}'?`)) return;
  try {
    const res = await api("/v1/skills/uninstall", {method: "POST", body: JSON.stringify({name})});
    if (res.ok) {
      alert("Skill uninstalled.");
      loadSkills();
      document.getElementById("skillDetail").className = "detail-panel";
    } else {
      alert("Uninstall failed: " + res.error);
    }
  } catch(e) {
    alert("Error: " + e.message);
  }
}

async function runSkill(skill) {
  const outputEl = document.getElementById("skillOutput");
  const outputText = document.getElementById("skillOutputText");
  outputEl.style.display = "block";
  outputText.textContent = "Running skill: " + (skill.name || skill.id || "?") + "...";
  try {
    const result = await api("/v1/skills/run", {method: "POST", body: JSON.stringify({skill: skill.name || skill.id})});
    outputText.textContent = JSON.stringify(result, null, 2);
  } catch(e) {
    outputText.textContent = "Error: " + (e.message || "Unknown error");
  }
}

