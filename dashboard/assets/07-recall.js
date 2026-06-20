// ===== RECALL =====
function tfScore(query, text) {
  if (!query || !text) return 0;
  const qTerms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const tTerms = text.toLowerCase().split(/\s+/);
  if (!qTerms.length || !tTerms.length) return 0;
  let score = 0;
  qTerms.forEach(qt => {
    let tf = 0;
    tTerms.forEach(tt => { if (tt.includes(qt) || qt.includes(tt)) tf++; });
    score += tf / tTerms.length;
  });
  return score / qTerms.length;
}

async function runRecall() {
  const q = document.getElementById("recallQuery").value.trim();
  if (!q) { alert("Enter a search query"); return; }
  syncMemoryProfileFields(getActiveMemoryProfile());
  const resultsEl = document.getElementById("recallResults");
  resultsEl.style.display = "block";
  resultsEl.innerHTML = "<span class='spinner'></span> Searching with TF scoring...";
  try {
    const result = await api("/v1/recall?q=" + encodeURIComponent(q) + "&top=20&" + memoryProfileQueryParam());
    if (!result.ok) { resultsEl.innerHTML = "Error: " + esc(result.error||"?"); return; }
    const facts = (result.facts || []).slice();

    resultsEl.innerHTML = "";
    const h3 = document.createElement("h3");
    h3.textContent = "Results for: \"" + q + "\" in profile \"" + (result.profile || getActiveMemoryProfile()) + "\" (" + facts.length + " matches)";
    resultsEl.appendChild(h3);

    if (!facts.length) {
      const p = document.createElement("p");
      p.textContent = "No matching facts found.";
      p.style.color = "var(--text2)";
      resultsEl.appendChild(p);
      return;
    }

    facts.forEach(item => {
      const f = item.fact || item;
      const card = document.createElement("div");
      card.style.cssText = "background:var(--bg3);border:1px solid var(--accent);border-radius:4px;padding:8px 12px;margin-top:6px";
      const scoreBadge = document.createElement("span");
      const score = item.score || tfScore(q, (f.key || "") + " " + (f.value || "") + " " + (f.tags || []).join(" "));
      scoreBadge.className = "badge " + (score > 0.3 ? "ok" : score > 0.1 ? "warn" : "info");
      scoreBadge.textContent = "Score: " + (score * 100).toFixed(1) + "%";
      const keySpan = document.createElement("strong");
      keySpan.textContent = f.key || "?";
      const valSpan = document.createElement("span");
      valSpan.textContent = " " + (f.value || "");
      valSpan.style.color = "var(--text2)";
      card.appendChild(scoreBadge);
      card.appendChild(document.createTextNode(" "));
      card.appendChild(keySpan);
      card.appendChild(document.createTextNode(": "));
      card.appendChild(valSpan);
      if (f.profile) {
        card.appendChild(document.createElement("br"));
        const profile = document.createElement("span");
        profile.className = "mono";
        profile.style.color = "var(--text2)";
        profile.textContent = "profile=" + f.profile;
        card.appendChild(profile);
      }
      if (f.tags && f.tags.length) {
        card.appendChild(document.createTextNode(" "));
        f.tags.forEach(t => {
          const tb = document.createElement("span");
          tb.className = "badge ok";
          tb.textContent = t;
          card.appendChild(tb);
          card.appendChild(document.createTextNode(" "));
        });
      }
      resultsEl.appendChild(card);
    });
  } catch(e) {
    resultsEl.innerHTML = "Error: " + esc(e.message||"Unknown");
  }
}

async function memoryDigestFull() {
  syncMemoryProfileFields(getActiveMemoryProfile());
  const panel = document.getElementById("digestResults");
  panel.style.display = "block";
  panel.innerHTML = "<span class='spinner'></span> Generating memory digest...";
  try {
    const result = await api("/v1/recall/digest?" + memoryProfileQueryParam());
    if (!result.ok) { panel.innerHTML = "Error: " + esc(result.error||"?"); return; }
    const pre = document.createElement("pre");
    pre.className = "mono";
    pre.style.whiteSpace = "pre-wrap";
    pre.textContent = result.digest || "";
    panel.innerHTML = "";
    const h3 = document.createElement("h3");
    h3.textContent = "Memory Digest";
    panel.appendChild(h3);
    panel.appendChild(pre);
  } catch(e) {
    panel.innerHTML = "Error: " + esc(e.message||"Unknown");
  }
}
