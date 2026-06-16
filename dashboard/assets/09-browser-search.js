// ===== BROWSER =====
async function browserSearch() {
  const q = document.getElementById("searchQuery").value.trim();
  const n = document.getElementById("searchCount").value;
  if (!q) return;
  const resultsEl = document.getElementById("searchResults");
  resultsEl.innerHTML = "<div class='card'><span class='spinner'></span> Searching...</div>";
  try {
    const result = await api("/v1/browser/search?q=" + encodeURIComponent(q) + "&n=" + n);
    if (!result.ok || !result.results) {
      resultsEl.innerHTML = "<div class='card'>Error: " + esc(result.error||"?") + "</div>";
      return;
    }
    resultsEl.innerHTML = "";
    result.results.forEach((r,i) => {
      const card = document.createElement("div");
      card.className = "card";
      const strong = document.createElement("strong");
      strong.textContent = (i+1) + ". " + (r.title||"");
      card.appendChild(strong);
      card.appendChild(document.createElement("br"));
      const a = document.createElement("a");
      a.href = r.url;
      a.target = "_blank";
      a.style.cssText = "color:var(--purple);font-size:12px";
      a.textContent = r.url || "";
      card.appendChild(a);
      card.appendChild(document.createElement("br"));
      const span = document.createElement("span");
      span.style.cssText = "font-size:12px;color:var(--text2)";
      span.textContent = r.snippet || "";
      card.appendChild(span);
      resultsEl.appendChild(card);
    });
  } catch(e) {
    resultsEl.innerHTML = "<div class='card'>Search error: " + esc(e.message||"Unknown") + "</div>";
  }
}

