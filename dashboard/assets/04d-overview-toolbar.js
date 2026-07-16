// ===== OVERVIEW TOOLBAR =====
//
// Toolbar controls added by the Overview redesign:
//   - Reload button (wired via HTML onclick to refreshOverview)
//   - auto-refresh checkbox with pulsing indicator dot
//   - interval selector (5/15/30/60 seconds)
//   - meta line reporting last-refresh time + load duration
//
// Written as a wrapper module so we DON'T touch 04-overview.js
// (which already defines refreshOverview). Instead we intercept
// the function once at load and record the refresh outcome.
// Same composition trick as the Audit tab's live-tail wiring:
// original loader remains a single-purpose function, the polish
// lives beside it.
//
// Every id referenced here matches the ids embedded in
// body-01-overview.html. Missing ids -> silent no-op, so the
// module is safe to load on any legacy dashboard build that
// hasn't been reissued yet.

(function () {
  "use strict";

  var _timer = null;
  var _originalRefresh = null;
  var _lastDurationMs = null;
  var _lastError = null;
  var _lastRefreshAt = null;

  function _q(id) { return document.getElementById(id); }

  function _fmtTime(d) {
    if (!(d instanceof Date)) return "--:--:--";
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function _pulseDot(err) {
    var dot = _q("overviewRefreshDot");
    if (!dot) return;
    dot.classList.remove("on", "err");
    // Restart animation by forcing a reflow before re-adding class.
    void dot.offsetWidth;
    dot.classList.add(err ? "err" : "on");
    if (_timer === null) {
      // manual reload -- fade the dot back to invisible after one pulse.
      window.setTimeout(function () {
        if (dot) dot.classList.remove("on", "err");
      }, 1500);
    }
  }

  function _renderMeta() {
    var meta = _q("overviewMeta");
    if (!meta) return;
    var parts = [];
    parts.push("Last refresh " + _fmtTime(_lastRefreshAt));
    if (_lastDurationMs !== null) parts.push(_lastDurationMs.toFixed(0) + " ms");
    if (_timer !== null) {
      var sel = _q("overviewInterval");
      var iv = sel ? sel.value : "15";
      parts.push("auto every " + iv + "s");
    } else {
      parts.push("manual");
    }
    if (_lastError) parts.push("last error: " + _lastError);
    meta.innerHTML = parts.map(function (p, i) {
      return (i === 0 ? "" : "<span class=\"sep\">·</span>") + p;
    }).join("");
  }

  function _wrappedRefresh() {
    if (typeof _originalRefresh !== "function") return Promise.resolve();
    var t0 = performance.now();
    _pulseDot(false);
    var ret;
    try {
      ret = _originalRefresh.apply(this, arguments);
    } catch (e) {
      _lastError = String(e && e.message || e);
      _lastDurationMs = performance.now() - t0;
      _lastRefreshAt = new Date();
      _pulseDot(true);
      _renderMeta();
      throw e;
    }
    if (ret && typeof ret.then === "function") {
      return ret.then(function (v) {
        _lastError = null;
        _lastDurationMs = performance.now() - t0;
        _lastRefreshAt = new Date();
        _renderMeta();
        return v;
      }, function (e) {
        _lastError = String(e && e.message || e);
        _lastDurationMs = performance.now() - t0;
        _lastRefreshAt = new Date();
        _pulseDot(true);
        _renderMeta();
        throw e;
      });
    }
    _lastError = null;
    _lastDurationMs = performance.now() - t0;
    _lastRefreshAt = new Date();
    _renderMeta();
    return ret;
  }

  function _rearmTimer() {
    if (_timer !== null) {
      window.clearInterval(_timer);
      _timer = null;
    }
    var box = _q("overviewAuto");
    if (!box || !box.checked) {
      _renderMeta();
      return;
    }
    var sel = _q("overviewInterval");
    var seconds = sel ? Math.max(1, parseInt(sel.value, 10) || 15) : 15;
    _timer = window.setInterval(function () {
      if (typeof window.refreshOverview === "function") {
        try {
          var p = window.refreshOverview();
          if (p && typeof p.catch === "function") p.catch(function () {});
        } catch (e) { /* swallow */ }
      }
    }, seconds * 1000);
    _renderMeta();
  }

  function _wireControls() {
    var box = _q("overviewAuto");
    var sel = _q("overviewInterval");
    if (box) box.addEventListener("change", _rearmTimer);
    if (sel) sel.addEventListener("change", _rearmTimer);
  }

  function _init() {
    if (typeof window.refreshOverview === "function" && _originalRefresh === null) {
      _originalRefresh = window.refreshOverview;
      window.refreshOverview = _wrappedRefresh;
    }
    _wireControls();
    _renderMeta();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _init);
  } else {
    _init();
  }

  // Expose for tests / diagnostic tinkering. Non-enumerable to keep
  // the global namespace tidy.
  Object.defineProperty(window, "__overviewToolbar", {
    value: {
      pulseDot: _pulseDot,
      renderMeta: _renderMeta,
      rearmTimer: _rearmTimer,
      getState: function () {
        return {
          hasTimer: _timer !== null,
          lastDurationMs: _lastDurationMs,
          lastRefreshAt: _lastRefreshAt,
          lastError: _lastError,
        };
      },
    },
    enumerable: false,
    writable: false,
  });
})();
