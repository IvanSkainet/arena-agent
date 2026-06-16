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

