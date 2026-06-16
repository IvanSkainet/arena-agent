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
  const resultsEl = document.getElementById("recallResults");
  resultsEl.style.display = "block";
  resultsEl.innerHTML = "<span class='spinner'></span> Searching with TF scoring...";
  try {
    const result = await api("/v1/memory");
    if (!result.ok) { resultsEl.innerHTML = "Error: " + esc(result.error||"?"); return; }
    const facts = (result.facts || []).map(f => {
      const text = (f.key + " " + f.value + " " + (f.tags||[]).join(" "));
      const score = tfScore(q, text);
      return {...f, score};
    }).filter(f => f.score > 0).sort((a,b) => b.score - a.score);

    resultsEl.innerHTML = "";
    const h3 = document.createElement("h3");
    h3.textContent = "Results for: \"" + q + "\" (" + facts.length + " matches)";
    resultsEl.appendChild(h3);

    if (!facts.length) {
      const p = document.createElement("p");
      p.textContent = "No matching facts found.";
      p.style.color = "var(--text2)";
      resultsEl.appendChild(p);
      return;
    }

    facts.forEach(f => {
      const card = document.createElement("div");
      card.style.cssText = "background:var(--bg3);border:1px solid var(--accent);border-radius:4px;padding:8px 12px;margin-top:6px";
      const scoreBadge = document.createElement("span");
      scoreBadge.className = "badge " + (f.score > 0.3 ? "ok" : f.score > 0.1 ? "warn" : "info");
      scoreBadge.textContent = "Score: " + (f.score * 100).toFixed(1) + "%";
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
  const panel = document.getElementById("digestResults");
  panel.style.display = "block";
  panel.innerHTML = "<span class='spinner'></span> Generating memory digest...";
  try {
    const result = await api("/v1/memory");
    if (!result.ok) { panel.innerHTML = "Error: " + esc(result.error||"?"); return; }
    const facts = result.facts || [];
    const tagCounts = {};
    const tagKeys = {};
    facts.forEach(f => {
      (f.tags||[]).forEach(t => {
        tagCounts[t] = (tagCounts[t]||0) + 1;
        if (!tagKeys[t]) tagKeys[t] = [];
        tagKeys[t].push(f.key);
      });
    });

    let output = "=== MEMORY DIGEST ===\n";
    output += "Total Facts: " + facts.length + "\n";
    output += "Unique Tags: " + Object.keys(tagCounts).length + "\n\n";
    output += "--- By Tag ---\n";
    Object.entries(tagCounts).sort((a,b)=>b[1]-a[1]).forEach(([t,c]) => {
      output += "[" + t + "] (" + c + " facts)\n";
      (tagKeys[t]||[]).slice(0,5).forEach(k => { output += "  - " + k + "\n"; });
      if (tagKeys[t].length > 5) output += "  ... and " + (tagKeys[t].length - 5) + " more\n";
    });
    output += "\n--- Recent Facts ---\n";
    facts.slice(0, 20).forEach(f => {
      output += (f.key||"?") + ": " + (f.value||"").slice(0, 100) + "\n";
    });

    const pre = document.createElement("pre");
    pre.className = "mono";
    pre.style.whiteSpace = "pre-wrap";
    pre.textContent = output;
    panel.innerHTML = "";
    const h3 = document.createElement("h3");
    h3.textContent = "Memory Digest";
    panel.appendChild(h3);
    panel.appendChild(pre);
  } catch(e) {
    panel.innerHTML = "Error: " + esc(e.message||"Unknown");
  }
}

