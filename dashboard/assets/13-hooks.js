// ===== HOOKS =====
async function loadHooks() {
  const container = document.getElementById("hooksContainer");
  container.innerHTML = "<span class='spinner'></span> Loading hooks...";
  try {
    const result = await api("/v1/hooks");
    if (!result.ok) { container.innerHTML = "<div class='card'>Error: " + esc(result.error||"?") + "</div>"; return; }
    const hooks = result.hooks || {};
    container.innerHTML = "";
    if (!Object.keys(hooks).length) {
      container.innerHTML = "<div class='card'>No hooks configured</div>";
      return;
    }
    Object.entries(hooks).forEach(([event, hookList]) => {
      const card = document.createElement("div");
      card.className = "card";
      const h3 = document.createElement("h3");
      h3.textContent = "Event: " + event;
      h3.style.color = "var(--yellow)";
      card.appendChild(h3);
      if (Array.isArray(hookList)) {
        hookList.forEach(h => {
          const div = document.createElement("div");
          div.style.cssText = "background:var(--bg3);padding:8px;border-radius:4px;margin-top:4px;font-size:12px";
          const pre = document.createElement("pre");
          pre.className = "mono";
          pre.style.whiteSpace = "pre-wrap";
          pre.textContent = JSON.stringify(h, null, 2);
          div.appendChild(pre);
          card.appendChild(div);
        });
      } else {
        const pre = document.createElement("pre");
        pre.className = "mono";
        pre.style.whiteSpace = "pre-wrap";
        pre.textContent = JSON.stringify(hookList, null, 2);
        card.appendChild(pre);
      }
      container.appendChild(card);
    });
  } catch(e) {
    container.innerHTML = "<div class='card'>Error loading hooks: " + esc(e.message||"Unknown") + "</div>";
  }
}

