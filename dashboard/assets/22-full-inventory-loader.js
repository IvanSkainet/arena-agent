// Full Inventory tab. Since v3.89.0 delegates all card rendering
// to the unified _hwRenderAll() in 03b-hw-cards.js -- same visuals
// as Doctor tab, no duplicated mapping. View toggle cycles through:
//   * cards    -- grid of _hwRender* cards
//   * rendered -- text -> Markdown -> HTML
//   * raw      -- plain monospace text
window._invViewMode = "cards";
window._invRawText = "";
window._invRaw = null;   // parsed /v1/inventory JSON
window._invHw = null;    // parsed /v1/hardware.hardware JSON

function _invWantedSet() {
  const boxes = Array.from(document.querySelectorAll(".inv-sec:checked"));
  if (!boxes.length) return null;
  if (boxes.some(b => b.value === "")) return null;   // "all" wins
  return new Set(boxes.map(b => b.value));
}

function _invRenderCurrent() {
  const out = document.getElementById("invOutput");
  if (!out) return;
  const text = window._invRawText || "";

  if (window._invViewMode === "raw") {
    out.style.whiteSpace = "pre-wrap";
    out.textContent = text;
    return;
  }
  if (window._invViewMode === "rendered") {
    out.style.whiteSpace = "pre-wrap";
    out.innerHTML = renderMarkdown(text);
    return;
  }
  // cards mode -- use the unified renderer. Prefer /v1/hardware (has
  // normalized cpu/gpu/memory) for known-normalized sections; merged
  // in with /v1/inventory as the base so probe-shaped sections (agent
  // facts/ctx) that only exist on the raw side are still rendered.
  out.style.whiteSpace = "normal";
  if (typeof _hwRenderAll !== "function") {
    out.textContent = text;
    return;
  }
  const merged = Object.assign({}, window._invRaw || {}, window._invHw || {});
  const html = _hwRenderAll(merged, _invWantedSet());
  if (!html) {
    out.textContent = text || "(no data)";
    return;
  }
  out.innerHTML =
    '<div style="display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">'
    + html + "</div>";
}

function toggleInvViewMode() {
  const modes = ["cards", "rendered", "raw"];
  const idx = modes.indexOf(window._invViewMode);
  window._invViewMode = modes[(idx + 1) % modes.length];
  const btn = document.getElementById("invViewModeBtn");
  if (btn) {
    const labels = {cards: "🎨 Cards", rendered: "📖 Rendered", raw: "📝 Raw"};
    btn.textContent = labels[window._invViewMode];
  }
  _invRenderCurrent();
}

function toggleFullInventory() {
  const card = document.getElementById("fullInventoryCard");
  if (!card) return;
  const btn = document.getElementById("invToggleBtn");
  if (card.style.display === "none") {
    card.style.display = "";
    if (btn) btn.textContent = "🙈 Hide Inventory";
    card.scrollIntoView({behavior: "smooth", block: "start"});
    // Populate the checkbox strip on first open, before firing the load.
    _invBuildCheckboxStrip().then(() => {
      const out = document.getElementById("invOutput");
      if (out && out.textContent.startsWith('Click "Load')) loadFullInventory();
    });
  } else {
    card.style.display = "none";
    if (btn) btn.textContent = "📋 Full Inventory";
  }
}

// v3.89.0: checkboxes are now auto-generated from the registry so
// adding a new probe backend-side lights up its section here at boot.
// The "all" checkbox is the first one and stays hardcoded in HTML.
async function _invBuildCheckboxStrip() {
  const strip = document.getElementById("invSectionStrip");
  if (!strip) return;
  if (strip.dataset.built === "1") return;
  const sections = await _hwLoadRegistry();
  // Group by category for readability.
  const byCat = {};
  sections.forEach(s => {
    (byCat[s.category || "other"] = byCat[s.category] || []).push(s);
  });
  const parts = [
    '<label><input type="checkbox" class="inv-sec" value="" checked> all</label>',
  ];
  ["hardware", "sensors", "agent", "runtime", "software", "other"].forEach(cat => {
    const items = byCat[cat] || [];
    items.forEach(s => {
      parts.push(
        '<label><input type="checkbox" class="inv-sec" value="'
        + s.name + '"> ' + (s.label || s.name) + '</label>'
      );
    });
  });
  strip.innerHTML = parts.join("");
  strip.dataset.built = "1";
}

async function loadFullInventory() {
  const out = document.getElementById("invOutput");
  const status = document.getElementById("invStatus");
  if (!out) return;
  out.textContent = "Loading...";
  if (status) { status.textContent = "loading"; status.className = "badge warn"; }
  const t0 = Date.now();

  const sections = Array.from(document.querySelectorAll(".inv-sec:checked"))
                        .map(c => c.value).filter(v => v);
  const allChecked = Array.from(document.querySelectorAll(".inv-sec:checked"))
                          .some(c => c.value === "");
  let url = "/v1/inventory?format=json&timeout=45";
  if (!allChecked && sections.length === 1) {
    url += "&section=" + encodeURIComponent(sections[0]);
  }

  try {
    const [r, rhw] = await Promise.all([api(url), api("/v1/hardware")]);
    const dt = ((Date.now() - t0) / 1000).toFixed(1);
    if (!r.ok) {
      out.textContent = "Error: " + (r.error || JSON.stringify(r));
      if (status) { status.textContent = "error"; status.className = "badge red"; }
      return;
    }
    window._invRaw = r.inventory || {};
    window._invHw = (rhw && rhw.ok) ? (rhw.hardware || {}) : {};
    window._invRawText = formatInventoryText(
      window._invRaw, allChecked ? null : sections
    );
    _invRenderCurrent();
    if (status) { status.textContent = `loaded in ${dt}s`; status.className = "badge ok"; }
  } catch (e) {
    out.textContent = "Network error: " + (e.message || e);
    if (status) { status.textContent = "network error"; status.className = "badge red"; }
  }
}
