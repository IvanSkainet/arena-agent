// ===== OVERVIEW GPU + RECENT ERRORS =====
//
// Two additional Overview cards driven off the existing
// /v1/hwinfo endpoint (which already exposes GPU utilization/
// temperature/VRAM and systemd_failed unit lists -- no new
// server endpoint was needed).
//
// The card containers are declared in body-01-overview.html
// (#gpuCard, #errCard). This module only knows how to fetch,
// pick apart the response, and paint the DOM.
//
// Fail-soft rules (per the dashboard-wide contract established
// by the Audit + Overview redesigns):
//   * No GPU section in the response -> hide the whole GPU card
//     silently. Users on GPU-less hosts don't get an empty widget.
//   * systemd not available (BSD, Windows) -> hide the errors
//     card. Same reasoning.
//   * Any fetch error -> keep the last-known state on screen and
//     do nothing loud. Toolbar meta line already reports errors
//     for the overall refresh; two more error banners here would
//     just add noise.
//
// Hooks itself into the Overview refresh cycle by wrapping
// window.refreshOverview (the same composition pattern
// 04d-overview-toolbar.js uses). Both wrappers stack cleanly:
// toolbar wrapper measures duration, this wrapper adds work
// inside the wrapped body.

(function () {
  "use strict";

  var _lastGpu = null;
  var _lastErr = null;

  function _q(id) { return document.getElementById(id); }

  function _fmtMb(n) {
    if (typeof n !== "number" || !isFinite(n) || n < 0) return "--";
    if (n < 1024) return n.toFixed(0) + " MB";
    return (n / 1024).toFixed(1) + " GB";
  }

  // ------------------------------------------------------------------
  // GPU card
  // ------------------------------------------------------------------
  function _renderGpu(gpu) {
    var card = _q("gpuCard");
    var empty = _q("gpuEmpty");
    var body = _q("gpuBody");
    var badge = _q("gpuBadge");
    if (!card) return;

    // No GPU data at all -- hide the card entirely so no-GPU hosts
    // don't see a placeholder.
    if (!gpu || typeof gpu !== "object" || !gpu.name) {
      card.style.display = "none";
      if (badge) badge.style.display = "none";
      // Also hide the parent H2. It sits immediately before the
      // card in the DOM tree; we tagged it with the badge id so
      // walking backwards is reliable.
      if (badge) {
        var h2 = badge.parentElement;
        if (h2 && h2.tagName === "H2") h2.style.display = "none";
      }
      return;
    }
    card.style.display = "";
    if (empty) empty.style.display = "none";
    if (body) body.style.display = "";
    if (badge) {
      badge.style.display = "";
      var h2 = badge.parentElement;
      if (h2 && h2.tagName === "H2") h2.style.display = "";
    }

    var nameEl = _q("gpuName");
    var driverEl = _q("gpuDriver");
    var utilBar = _q("gpuUtilBar");
    var utilText = _q("gpuUtilText");
    var vramBar = _q("gpuVramBar");
    var vramText = _q("gpuVramText");
    var tempEl = _q("gpuTempText");

    if (nameEl) nameEl.textContent = String(gpu.name || "--");
    if (driverEl) driverEl.textContent = String(gpu.driver || "--");

    var util = (typeof gpu.utilization_pct === "number") ? gpu.utilization_pct : null;
    if (utilBar) utilBar.style.width = (util !== null ? Math.max(0, Math.min(100, util)) : 0) + "%";
    if (utilText) utilText.textContent = (util !== null ? util.toFixed(0) + "%" : "n/a");

    var used = (typeof gpu.vram_used_mb === "number") ? gpu.vram_used_mb : null;
    var total = (typeof gpu.vram_total_mb === "number") ? gpu.vram_total_mb : (gpu.vram_mb || null);
    if (used !== null && total && total > 0) {
      var pct = Math.max(0, Math.min(100, (used / total) * 100));
      if (vramBar) vramBar.style.width = pct.toFixed(1) + "%";
      if (vramText) vramText.textContent = _fmtMb(used) + " / " + _fmtMb(total);
    } else {
      if (vramBar) vramBar.style.width = "0%";
      if (vramText) vramText.textContent = "n/a";
    }

    var temp = (typeof gpu.temperature_c === "number") ? gpu.temperature_c : null;
    if (tempEl) tempEl.textContent = (temp !== null ? temp + " °C" : "n/a");

    // Badge = summary at a glance. Hot >= 80 °C or util >= 90%
    // marks the card orange; otherwise green with "idle" / "busy".
    if (badge) {
      badge.classList.remove("hot", "ok");
      if ((temp !== null && temp >= 80) || (util !== null && util >= 90)) {
        badge.classList.add("hot");
        badge.textContent = (temp !== null ? temp + "°C " : "") +
                            (util !== null ? util + "%" : "");
      } else {
        badge.classList.add("ok");
        var label = (util !== null && util >= 20) ? "busy" : "idle";
        badge.textContent = label + " · " + (temp !== null ? temp + "°C" : "?");
      }
    }
    _lastGpu = gpu;
  }

  // ------------------------------------------------------------------
  // Recent errors card
  // ------------------------------------------------------------------
  function _renderErrors(sys) {
    var card = _q("errCard");
    var empty = _q("errEmpty");
    var body = _q("errBody");
    var badge = _q("errBadge");
    var header = badge ? badge.parentElement : null;
    if (!card) return;

    if (!sys || sys.available === false) {
      // systemd unavailable (BSD/Windows) -- hide the card silently.
      card.style.display = "none";
      if (header && header.tagName === "H2") header.style.display = "none";
      return;
    }
    card.style.display = "";
    if (header && header.tagName === "H2") header.style.display = "";
    if (empty) empty.style.display = "none";
    if (body) body.style.display = "";

    var systemFailed = Array.isArray(sys.system_failed) ? sys.system_failed : [];
    var userFailed = Array.isArray(sys.user_failed) ? sys.user_failed : [];
    var total = systemFailed.length + userFailed.length;

    var sysCountEl = _q("errSystemCount");
    var userCountEl = _q("errUserCount");
    if (sysCountEl) sysCountEl.textContent = systemFailed.length + " failed";
    if (userCountEl) userCountEl.textContent = userFailed.length + " failed";

    if (badge) {
      badge.classList.remove("ok", "fail");
      badge.classList.add(total === 0 ? "ok" : "fail");
      badge.textContent = total === 0 ? "healthy" : (total + " failed");
    }

    var list = _q("errList");
    if (list) {
      // Rebuild list. Small counts (< 50) so no need for a virtual
      // scroller; just wipe and re-render.
      list.innerHTML = "";
      var items = [];
      systemFailed.forEach(function (u) { items.push(["system", u]); });
      userFailed.forEach(function (u) { items.push(["user", u]); });
      items.forEach(function (pair) {
        var scope = pair[0];
        var unit = pair[1] || {};
        var row = document.createElement("div");
        row.className = "err-item";

        var scopeEl = document.createElement("span");
        scopeEl.className = "scope";
        scopeEl.textContent = scope;
        row.appendChild(scopeEl);

        var unitEl = document.createElement("span");
        unitEl.className = "unit";
        unitEl.textContent = unit.unit || "(unknown)";
        row.appendChild(unitEl);

        if (unit.description) {
          var descEl = document.createElement("span");
          descEl.className = "desc";
          descEl.textContent = unit.description;
          row.appendChild(descEl);
        }
        list.appendChild(row);
      });
      if (items.length === 0) {
        var okRow = document.createElement("div");
        okRow.style.color = "var(--text2)";
        okRow.textContent = "All units healthy.";
        list.appendChild(okRow);
      }
    }
    _lastErr = sys;
  }

  // ------------------------------------------------------------------
  // Loader -- wraps window.refreshOverview to piggyback on the
  // existing refresh cycle. Falls back to standalone timer when
  // the wrapper isn't installed (e.g. legacy dashboard build).
  // ------------------------------------------------------------------
  async function _fetchAndRender() {
    try {
      // Use the same api() helper the other loaders use so bearer
      // auth is handled uniformly.
      var d = null;
      if (typeof window.api === "function") {
        d = await window.api("/v1/hwinfo");
      } else {
        var resp = await fetch("/v1/hwinfo", { credentials: "same-origin" });
        d = await resp.json();
      }
      var hw = (d && (d.hardware || d.hwinfo)) || {};
      _renderGpu(hw.gpu);
      _renderErrors(hw.systemd_failed);
    } catch (e) {
      // Fail-soft: keep last state on screen. Do not spam banners.
    }
  }

  var _origRefresh = null;
  function _install() {
    if (typeof window.refreshOverview === "function") {
      _origRefresh = window.refreshOverview;
      window.refreshOverview = function () {
        var ret = _origRefresh.apply(this, arguments);
        // Fire our fetch in the background -- do not block the
        // original refresh promise so the toolbar duration
        // measurement stays honest for the primary payload.
        _fetchAndRender();
        return ret;
      };
    } else {
      // No refreshOverview yet -- run a one-shot fetch so the card
      // is populated on first paint anyway.
      _fetchAndRender();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _install);
  } else {
    _install();
  }

  // Diagnostic hook.
  Object.defineProperty(window, "__overviewGpuErrors", {
    value: {
      renderGpu: _renderGpu,
      renderErrors: _renderErrors,
      fetch: _fetchAndRender,
      getState: function () {
        return { lastGpu: _lastGpu, lastErr: _lastErr };
      },
    },
    enumerable: false,
    writable: false,
  });
})();
