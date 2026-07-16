// Doctor tab: hardware inventory loader. All card rendering is
// delegated to _hwRenderAll() in 03b-hw-cards.js so Doctor and Full
// Inventory tabs stay in visual + logical sync.
async function doctorLoadHardware() {
  const target = _hwEl("hwCards");
  const rawEl = _hwEl("hwRawJson");
  const timeEl = _hwEl("hwGeneratedAt");
  if (target) target.innerHTML =
    '<div style="color:var(--text3);font-size:12px">Loading hardware inventory…</div>';
  try {
    const r = await api("/v1/hardware");
    if (!r || r.ok !== true) {
      target.innerHTML =
        '<div style="color:var(--red)">Hardware fetch failed: '
        + _hwEsc((r && r.error) || "unknown") + '</div>';
      return;
    }
    const hw = r.hardware || {};
    if (timeEl && hw.generated_at) {
      timeEl.textContent = "collected " + new Date(hw.generated_at).toLocaleString();
    }
    // Doctor tab shows every registered section that has a card
    // renderer. The unified renderer honours the same source shape
    // as Full Inventory, so we don't maintain a separate list here.
    const html = _hwRenderAll(hw, null);
    if (!html) {
      target.innerHTML =
        '<div style="color:var(--warning-text)">Backend returned empty hardware payload.</div>';
    } else {
      target.innerHTML = html;
    }
    if (rawEl) rawEl.textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    target.innerHTML =
      '<div style="color:var(--red)">Hardware fetch failed: '
      + _hwEsc(e && e.message || e) + '</div>';
  }
}

// Auto-run once when the Doctor tab first becomes visible.
(function () {
  let ran = false;
  function _once() {
    if (ran) return;
    const t = document.getElementById("tab-doctor");
    if (t && t.style.display !== "none") {
      ran = true;
      try { doctorLoadHardware(); } catch (_) {}
    }
  }
  document.addEventListener("click", (ev) => {
    if (!ev || !ev.target) return;
    const target = ev.target.closest &&
      ev.target.closest('[onclick*="doctor" i], [onclick*="Doctor" i], .tab-btn');
    if (target) setTimeout(_once, 50);
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded",
      () => setTimeout(_once, 500), {once: true});
  } else {
    setTimeout(_once, 500);
  }
})();
