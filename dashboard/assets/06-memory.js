// ===== MEMORY =====
async function loadMemory() {
  const q = document.getElementById("memSearch").value;
  const tbody = document.getElementById("memoryTable");
  try {
    const result = await api("/v1/memory" + (q ? "?q=" + encodeURIComponent(q) : ""));
    if (!result.ok) { tbody.innerHTML = "<tr><td colspan='5'>Error: " + esc(result.error||"?") + "</td></tr>"; return; }
    if (!result.facts || !result.facts.length) { tbody.innerHTML = "<tr><td colspan='5'>No facts found</td></tr>"; return; }
    tbody.innerHTML = "";
    result.facts.forEach(f => {
      const tr = document.createElement("tr");
      const tdKey = document.createElement("td");
      const strong = document.createElement("strong");
      strong.textContent = f.key || "";
      tdKey.appendChild(strong);
      const tdVal = document.createElement("td");
      tdVal.textContent = f.value || "";
      const tdTags = document.createElement("td");
      (f.tags || []).forEach(t => {
        const badge = document.createElement("span");
        badge.className = "badge ok";
        badge.textContent = t;
        tdTags.appendChild(badge);
        tdTags.appendChild(document.createTextNode(" "));
      });
      const tdTime = document.createElement("td");
      tdTime.className = "mono";
      tdTime.textContent = relTime(f.timestamp);
      const tdActions = document.createElement("td");
      const delBtn = document.createElement("button");
      delBtn.className = "danger sm";
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", () => deleteMemory(f.key));
      tdActions.appendChild(delBtn);
      tr.appendChild(tdKey); tr.appendChild(tdVal); tr.appendChild(tdTags); tr.appendChild(tdTime); tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = "<tr><td colspan='5'>Error loading memory: " + esc(e.message||"Unknown") + "</td></tr>";
  }
}

async function addMemory() {
  const key = document.getElementById("memKey").value.trim();
  const value = document.getElementById("memValue").value.trim();
  const tags = document.getElementById("memTags").value.split(",").map(t=>t.trim()).filter(Boolean);
  if (!key || !value) return alert("Key and value required");
  try {
    const result = await api("/v1/memory", {method: "POST", body: JSON.stringify({key, value, tags})});
    if (result.ok) {
      document.getElementById("memKey").value = "";
      document.getElementById("memValue").value = "";
      document.getElementById("memTags").value = "";
      loadMemory();
    } else {
      alert("Error: " + (result.error||"?"));
    }
  } catch(e) {
    alert("Error adding memory: " + (e.message||"Unknown error"));
  }
}

async function deleteMemory(key) {
  if (!confirm("Delete fact: " + key + "?")) return;
  try {
    const result = await api("/v1/memory", {method: "DELETE", body: JSON.stringify({key})});
    if (result.ok) loadMemory();
    else alert("Error: " + (result.error||"?"));
  } catch(e) {
    alert("Error deleting: " + (e.message||"Unknown error"));
  }
}

async function memoryDigest() {
  const panel = document.getElementById("memoryDigestPanel");
  panel.style.display = "block";
  panel.innerHTML = "<span class='spinner'></span> Generating digest...";
  try {
    const result = await api("/v1/memory");
    if (!result.ok) { panel.innerHTML = "Error: " + esc(result.error||"?"); return; }
    const facts = result.facts || [];
    const tagCounts = {};
    let output = "Memory Digest: " + facts.length + " facts\n\n";
    facts.forEach(f => {
      output += "  " + (f.key||"?") + ": " + (f.value||"").slice(0,80) + "\n";
      (f.tags||[]).forEach(t => { tagCounts[t] = (tagCounts[t]||0) + 1; });
    });
    output += "\nTag Summary:\n";
    Object.entries(tagCounts).sort((a,b)=>b[1]-a[1]).forEach(([t,c]) => { output += "  [" + t + "] x" + c + "\n"; });
    const pre = document.createElement("pre");
    pre.className = "mono";
    pre.style.whiteSpace = "pre-wrap";
    pre.textContent = output;
    panel.innerHTML = "";
    panel.appendChild(pre);
  } catch(e) {
    panel.innerHTML = "Error: " + esc(e.message||"Unknown");
  }
}

async function recallFromMemory() {
  const q = document.getElementById("memSearch").value.trim();
  if (!q) { alert("Enter a search query first"); return; }
  // Navigate to recall tab
  document.querySelectorAll(".sidebar nav a").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  document.querySelector('[data-tab="recall"]').classList.add("active");
  document.getElementById("tab-recall").classList.add("active");
  document.getElementById("recallQuery").value = q;
  runRecall();
}

