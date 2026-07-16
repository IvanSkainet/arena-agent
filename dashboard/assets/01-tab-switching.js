// ===== TAB SWITCHING (v3.90.0 unified) =====
// Both the sidebar nav and the on-switch dispatcher read from
// window.ARENA_TABS (00-tabs-registry.js). Zero hardcoded tab
// names here -- adding one is a single-line edit in the registry.

(function () {
  const tabs = window.ARENA_TABS || [];

  // 1) Build the sidebar nav from the registry.
  const nav = document.getElementById("arenaSidebarNav");
  if (nav && !nav.dataset.built) {
    nav.innerHTML = tabs.map((t, idx) => {
      const cls = idx === 0 ? ' class="active"' : "";
      return `<a${cls} data-tab="${t.name}">${t.icon || ""} ${t.label}</a>`;
    }).join("\n");
    nav.dataset.built = "1";
  }

  // 2) Attach click dispatcher. Uses event delegation so links
  //    added after boot (never yet, but future-proof) still work.
  document.addEventListener("click", (ev) => {
    const link = ev.target.closest && ev.target.closest(".sidebar nav a[data-tab]");
    if (!link) return;

    const prevActive = document.querySelector(".sidebar nav a.active");
    const prevName = prevActive ? prevActive.dataset.tab : null;

    document.querySelectorAll(".sidebar nav a").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    link.classList.add("active");
    const tabName = link.dataset.tab;
    window.activeTab = tabName;

    const el = document.getElementById("tab-" + tabName);
    if (el) el.classList.add("active");

    // Fire onHide for the previous tab.
    if (prevName && prevName !== tabName) {
      const prev = window.arenaTabByName && window.arenaTabByName(prevName);
      if (prev && typeof prev.onHide === "function") {
        try { prev.onHide(); } catch (e) { console.warn("onHide", prevName, e); }
      }
    }
    // Fire onShow for the new one.
    const tab = window.arenaTabByName && window.arenaTabByName(tabName);
    if (tab && typeof tab.onShow === "function") {
      try { tab.onShow(); } catch (e) { console.warn("onShow", tabName, e); }
    }
  });
})();
