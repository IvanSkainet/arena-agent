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

