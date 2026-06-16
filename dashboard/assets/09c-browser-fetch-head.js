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

