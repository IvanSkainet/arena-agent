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

async function browserRead() {
  const url = document.getElementById("readUrl").value.trim();
  if (!url) return;
  const readEl = document.getElementById("readResult");
  readEl.innerHTML = "<div class='card'><span class='spinner'></span> Reading...</div>";
  try {
    const result = await api("/v1/browser/read?url=" + encodeURIComponent(url));
    if (!result.ok) { readEl.innerHTML = "<div class='card'>Error: " + esc(result.error||"?") + "</div>"; return; }
    readEl.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    const h2 = document.createElement("h2");
    h2.textContent = result.title || "No title";
    card.appendChild(h2);
    const pre = document.createElement("pre");
    pre.className = "mono";
    pre.style.cssText = "white-space:pre-wrap;max-height:400px;overflow-y:auto";
    pre.textContent = result.text || "";
    card.appendChild(pre);
    readEl.appendChild(card);
  } catch(e) {
    readEl.innerHTML = "<div class='card'>Read error: " + esc(e.message||"Unknown") + "</div>";
  }
}

async function browserDump() {
  const url = document.getElementById("readUrl").value.trim();
  if (!url) return alert("Enter a URL first");
  const dumpEl = document.getElementById("dumpResult");
  dumpEl.innerHTML = "<div class='card'><span class='spinner'></span> Dumping page...</div>";
  try {
    const result = await api("/v1/browser/dump?url=" + encodeURIComponent(url));
    if (!result.ok) { dumpEl.innerHTML = "<div class='card'>Error: " + esc(result.error||"?") + "</div>"; return; }
    dumpEl.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    const h2 = document.createElement("h2");
    h2.textContent = "Dump: " + url;
    card.appendChild(h2);
    // Show extracted links
    if (result.links && result.links.length) {
      const h3 = document.createElement("h3");
      h3.textContent = "Extracted Links (" + result.links.length + ")";
      card.appendChild(h3);
      const linkDiv = document.createElement("div");
      linkDiv.className = "link-list";
      result.links.forEach(l => {
        const a = document.createElement("a");
        a.href = typeof l === "string" ? l : (l.url || "");
        a.target = "_blank";
        a.textContent = typeof l === "string" ? l : (l.text || l.url || "");
        linkDiv.appendChild(a);
      });
      card.appendChild(linkDiv);
    }
    if (result.text) {
      const h3 = document.createElement("h3");
      h3.textContent = "Page Content";
      card.appendChild(h3);
      const pre = document.createElement("pre");
      pre.className = "mono";
      pre.style.cssText = "white-space:pre-wrap;max-height:300px;overflow-y:auto";
      pre.textContent = result.text;
      card.appendChild(pre);
    }
    dumpEl.appendChild(card);
  } catch(e) {
    dumpEl.innerHTML = "<div class='card'>Dump error: " + esc(e.message||"Unknown") + "</div>";
  }
}

async function browserFetch() {
  const url = document.getElementById("readUrl").value.trim();
  if (!url) return alert("Enter a URL first");
  const readEl = document.getElementById("readResult");
  readEl.innerHTML = "<div class='card'><span class='spinner'></span> Fetching raw content...</div>";
  try {
    const result = await api("/v1/browser/fetch?url=" + encodeURIComponent(url));
    if (!result.ok) { readEl.innerHTML = "<div class='card'>Error: " + esc(result.error||"?") + "</div>"; return; }
    readEl.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    const h2 = document.createElement("h2");
    h2.textContent = "Fetch: " + url;
    card.appendChild(h2);
    const pre = document.createElement("pre");
    pre.className = "mono";
    pre.style.cssText = "white-space:pre-wrap;max-height:400px;overflow-y:auto";
    pre.textContent = result.content || result.text || JSON.stringify(result, null, 2);
    card.appendChild(pre);
    readEl.appendChild(card);
  } catch(e) {
    readEl.innerHTML = "<div class='card'>Fetch error: " + esc(e.message||"Unknown") + "</div>";
  }
}

async function browserHead() {
  const url = document.getElementById("readUrl").value.trim();
  if (!url) return alert("Enter a URL first");
  const headEl = document.getElementById("headResult");
  headEl.innerHTML = "<div class='card'><span class='spinner'></span> Getting headers...</div>";
  try {
    const result = await api("/v1/browser/head?url=" + encodeURIComponent(url));
    if (!result.ok) { headEl.innerHTML = "<div class='card'>Error: " + esc(result.error||"?") + "</div>"; return; }
    headEl.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    const h2 = document.createElement("h2");
    h2.textContent = "HEAD: " + url;
    card.appendChild(h2);
    // Show response headers
    if (result.headers) {
      const table = document.createElement("table");
      table.className = "hdr-table";
      Object.entries(result.headers).forEach(([k,v]) => {
        const tr = document.createElement("tr");
        const td1 = document.createElement("td");
        td1.textContent = k;
        const td2 = document.createElement("td");
        td2.className = "mono";
        td2.textContent = v;
        tr.appendChild(td1); tr.appendChild(td2);
        table.appendChild(tr);
      });
      card.appendChild(table);
    }
    if (result.status) {
      const p = document.createElement("p");
      p.style.marginTop = "8px";
      p.innerHTML = "Status: <strong>" + esc(result.status) + "</strong>";
      card.appendChild(p);
    }
    headEl.appendChild(card);
  } catch(e) {
    headEl.innerHTML = "<div class='card'>HEAD error: " + esc(e.message||"Unknown") + "</div>";
  }
}

async function browserScreenshot() {
  const url = document.getElementById("readUrl").value.trim();
  if (!url) return alert("Enter a URL first");
  const readEl = document.getElementById("readResult");
  readEl.innerHTML = "<div class='card'><span class='spinner'></span> Taking screenshot...</div>";
  try {
    const result = await api("/v1/exec", {method: "POST", body: JSON.stringify({cmd: "headless-chrome-screenshot " + url, timeout: 30})});
    if (!result.ok) { readEl.innerHTML = "<div class='card'>Error: " + esc(result.error||"?") + "</div>"; return; }
    readEl.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    const h2 = document.createElement("h2");
    h2.textContent = "Screenshot: " + url;
    card.appendChild(h2);
    const pre = document.createElement("pre");
    pre.className = "mono";
    pre.style.cssText = "white-space:pre-wrap;max-height:400px;overflow-y:auto";
    pre.textContent = result.stdout || "Screenshot output not available";
    card.appendChild(pre);
    readEl.appendChild(card);
  } catch(e) {
    readEl.innerHTML = "<div class='card'>Screenshot error: " + esc(e.message||"Unknown") + "</div>";
  }
}

