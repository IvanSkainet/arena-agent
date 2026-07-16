// ===== MISSIONS TOOLBAR =====
//
// Wraps the existing window.loadMissions() with:
//   - refresh dot pulse (green on success, red on error)
//   - meta line: last-refresh time, duration, mode (manual/auto),
//     last error if any
//   - auto-refresh timer driven by the DOM interval selector
//
// Same composition trick 04d-overview-toolbar.js uses for
// Overview: wrap the primary loader, don't redefine it. Missing
// window.loadMissions is treated as a no-op so a stripped-down
// dashboard build still boots.

(function () {
  "use strict";

  var _timer = null;
  var _originalLoad = null;
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
    var dot = _q("missionsRefreshDot");
    if (!dot) return;
    dot.classList.remove("on", "err");
    void dot.offsetWidth;
    dot.classList.add(err ? "err" : "on");
    if (_timer === null) {
      window.setTimeout(function () {
        if (dot) dot.classList.remove("on", "err");
      }, 1500);
    }
  }

  function _renderMeta() {
    var meta = _q("missionsMeta");
    if (!meta) return;
    var parts = [];
    parts.push("Last refresh " + _fmtTime(_lastRefreshAt));
    if (_lastDurationMs !== null) parts.push(_lastDurationMs.toFixed(0) + " ms");
    if (_timer !== null) {
      var sel = _q("missionsInterval");
      var iv = sel ? sel.value : "15";
      parts.push("auto every " + iv + "s");
    } else {
      parts.push("manual");
    }
    if (_lastError) parts.push("last error: " + _lastError);
    meta.innerHTML = parts.map(function (p, i) {
      return (i === 0 ? "" : '<span class="sep">·</span>') + p;
    }).join("");
  }

  function _wrappedLoad() {
    if (typeof _originalLoad !== "function") return Promise.resolve();
    var t0 = performance.now();
    _pulseDot(false);
    var ret;
    try {
      ret = _originalLoad.apply(this, arguments);
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
    var box = _q("missionsAuto");
    if (!box || !box.checked) { _renderMeta(); return; }
    var sel = _q("missionsInterval");
    var seconds = sel ? Math.max(1, parseInt(sel.value, 10) || 15) : 15;
    _timer = window.setInterval(function () {
      if (typeof window.loadMissions === "function") {
        try {
          var p = window.loadMissions();
          if (p && typeof p.catch === "function") p.catch(function () {});
        } catch (e) { /* swallow */ }
      }
    }, seconds * 1000);
    _renderMeta();
  }

  function _wireControls() {
    var box = _q("missionsAuto");
    var sel = _q("missionsInterval");
    if (box) box.addEventListener("change", _rearmTimer);
    if (sel) sel.addEventListener("change", _rearmTimer);
  }

  function _init() {
    if (typeof window.loadMissions === "function" && _originalLoad === null) {
      _originalLoad = window.loadMissions;
      window.loadMissions = _wrappedLoad;
    }
    _wireControls();
    _renderMeta();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _init);
  } else {
    _init();
  }

  Object.defineProperty(window, "__missionsToolbar", {
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
