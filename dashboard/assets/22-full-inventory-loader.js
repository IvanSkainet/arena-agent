// ===== Full Inventory (v1.6.3) =====
function toggleFullInventory() {
  const card = document.getElementById("fullInventoryCard");
  if (!card) return;
  const btn = document.getElementById("invToggleBtn");
  if (card.style.display === "none") {
    card.style.display = "";
    if (btn) btn.textContent = "🙈 Hide Inventory";
    card.scrollIntoView({behavior: "smooth", block: "start"});
    // Auto-load on first open
    const out = document.getElementById("invOutput");
    if (out && out.textContent.startsWith('Click "Load')) loadFullInventory();
  } else {
    card.style.display = "none";
    if (btn) btn.textContent = "📋 Full Inventory";
  }
}

async function loadFullInventory() {
  const out = document.getElementById("invOutput");
  const status = document.getElementById("invStatus");
  if (!out) return;
  out.textContent = "Loading...";
  if (status) { status.textContent = "loading"; status.className = "badge warn"; }
  const t0 = Date.now();

  // Determine which sections are selected
  const sections = Array.from(document.querySelectorAll(".inv-sec:checked"))
                        .map(c => c.value).filter(v => v);
  // "all" wins (no section filter)
  const allChecked = Array.from(document.querySelectorAll(".inv-sec:checked"))
                          .some(c => c.value === "");
  let url = "/v1/inventory?format=json&timeout=45";
  if (!allChecked && sections.length === 1) {
    url += "&section=" + encodeURIComponent(sections[0]);
  }

  try {
    const r = await api(url);
    const dt = ((Date.now() - t0) / 1000).toFixed(1);
    if (!r.ok) {
      out.textContent = "Error: " + (r.error || JSON.stringify(r));
      if (status) { status.textContent = "error"; status.className = "badge red"; }
      return;
    }
    const inv = r.inventory || {};
    // If multiple sections asked, filter client-side
    const text = formatInventoryText(inv, allChecked ? null : sections);
    out.textContent = text;
    if (status) { status.textContent = `loaded in ${dt}s`; status.className = "badge ok"; }
  } catch (e) {
    out.textContent = "Network error: " + (e.message || e);
    if (status) { status.textContent = "network error"; status.className = "badge red"; }
  }
}

