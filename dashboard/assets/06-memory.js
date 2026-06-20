// ===== MEMORY =====
function getActiveMemoryProfile() {
  const mem = document.getElementById("memProfile");
  const recall = document.getElementById("recallProfile");
  const value = (mem && mem.value) || (recall && recall.value) || localStorage.getItem("arenaMemoryProfile") || "default";
  const trimmed = (value || "").trim();
  return trimmed || "default";
}

function syncMemoryProfileFields(value) {
  const normalized = (value || "").trim() || "default";
  const mem = document.getElementById("memProfile");
  const recall = document.getElementById("recallProfile");
  if (mem && mem.value !== normalized) mem.value = normalized;
  if (recall && recall.value !== normalized) recall.value = normalized;
  localStorage.setItem("arenaMemoryProfile", normalized);
}

function memoryProfileQueryParam() {
  const profile = getActiveMemoryProfile();
  return "profile=" + encodeURIComponent(profile);
}

async function loadMemory() {
  syncMemoryProfileFields(getActiveMemoryProfile());
  const q = document.getElementById("memSearch").value;
  const tbody = document.getElementById("memoryTable");
  try {
    const query = [memoryProfileQueryParam()];
    if (q) query.push("q=" + encodeURIComponent(q));
    const result = await api("/v1/memory?" + query.join("&"));
    if (!result.ok) { tbody.innerHTML = "<tr><td colspan='5'>Error: " + esc(result.error||"?") + "</td></tr>"; return; }
    if (!result.facts || !result.facts.length) { tbody.innerHTML = "<tr><td colspan='5'>No facts found for profile: " + esc(result.profile||"default") + "</td></tr>"; return; }
    tbody.innerHTML = "";
    result.facts.forEach(f => {
      const tr = document.createElement("tr");
      const tdKey = document.createElement("td");
      const strong = document.createElement("strong");
      strong.textContent = f.key || "";
      tdKey.appendChild(strong);
      if (f.profile) {
        tdKey.appendChild(document.createElement("br"));
        const small = document.createElement("span");
        small.className = "mono";
        small.style.color = "var(--text2)";
        small.textContent = f.profile;
        tdKey.appendChild(small);
      }
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
      delBtn.addEventListener("click", () => deleteMemory(f.key, f.profile || getActiveMemoryProfile()));
      tdActions.appendChild(delBtn);
      tr.appendChild(tdKey); tr.appendChild(tdVal); tr.appendChild(tdTags); tr.appendChild(tdTime); tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = "<tr><td colspan='5'>Error loading memory: " + esc(e.message||"Unknown") + "</td></tr>";
  }
}

async function addMemory() {
  const profile = getActiveMemoryProfile();
  syncMemoryProfileFields(profile);
  const key = document.getElementById("memKey").value.trim();
  const value = document.getElementById("memValue").value.trim();
  const tags = document.getElementById("memTags").value.split(",").map(t=>t.trim()).filter(Boolean);
  if (!key || !value) return alert("Key and value required");
  try {
    const result = await api("/v1/memory", {method: "POST", body: JSON.stringify({profile, key, value, tags})});
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

async function deleteMemory(key, profile) {
  if (!confirm("Delete fact: " + key + " from profile " + profile + "?")) return;
  try {
    const result = await api("/v1/memory", {method: "DELETE", body: JSON.stringify({profile, key})});
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
    const result = await api("/v1/recall/digest?" + memoryProfileQueryParam());
    if (!result.ok) { panel.innerHTML = "Error: " + esc(result.error||"?"); return; }
    const pre = document.createElement("pre");
    pre.className = "mono";
    pre.style.whiteSpace = "pre-wrap";
    pre.textContent = result.digest || "";
    panel.innerHTML = "";
    panel.appendChild(pre);
  } catch(e) {
    panel.innerHTML = "Error: " + esc(e.message||"Unknown");
  }
}

async function recallFromMemory() {
  const q = document.getElementById("memSearch").value.trim();
  if (!q) { alert("Enter a search query first"); return; }
  syncMemoryProfileFields(getActiveMemoryProfile());
  document.querySelectorAll(".sidebar nav a").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  document.querySelector('[data-tab="recall"]').classList.add("active");
  document.getElementById("tab-recall").classList.add("active");
  document.getElementById("recallQuery").value = q;
  runRecall();
}
