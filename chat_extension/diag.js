// Arena Chat Bridge — diagnostics helpers (v0.14.2).
//
// Split out of content.js when adding the ring buffer + late-submit
// poller pushed the file over the 700-line project modularity
// threshold. Same sibling-module pattern the bridge's Python side
// uses for arena/observability/redact.py etc.
//
// Exposes three helpers on window (MV3 content scripts cannot import
// ES modules today, so window is the only shared surface). Loaded
// before content.js in manifest.json so they exist by the time
// mountControls / arenaInsertAndSubmit reach for them.
//
//   _arenaDiagPushEvent(evt)  -- append to ring buffer (cap 20)
//   arenaDiagRecentEvents()   -- copy of the ring buffer
//   arenaWaitForSubmit(a, ms) -- poll adapter.submitSelectors until
//                                one is enabled + visible, or timeout
//
// The ring buffer surfaces user-message skips, late-submit rescans
// and future instrumentation via scanPageDiagnostics.events_recent,
// so bug reports can inspect what the scanner was doing.

(function () {
  'use strict';

  const _ARENA_DIAG_EVENTS_MAX = 20;
  const _arenaDiagEvents = [];

  function _arenaDiagPushEvent(evt) {
    try {
      const record = Object.assign({ t: Date.now() }, evt || {});
      _arenaDiagEvents.push(record);
      if (_arenaDiagEvents.length > _ARENA_DIAG_EVENTS_MAX) {
        _arenaDiagEvents.shift();
      }
    } catch (_e) { /* diagnostics must never break the scanner */ }
  }

  async function arenaWaitForSubmit(adapter, maxMs) {
    const cap = Number.isFinite(maxMs) ? maxMs : 2000;
    const step = 300;
    const start = Date.now();
    const selectors = (adapter && adapter.submitSelectors) || [];
    while (Date.now() - start < cap) {
      for (const sel of selectors) {
        let btn = null;
        try { btn = document.querySelector(sel); } catch (_e) { /* skip */ }
        if (btn && !btn.disabled && btn.offsetParent !== null) {
          _arenaDiagPushEvent({
            kind: 'submit_late_found',
            adapter: adapter?.name || '',
            selector: sel,
            waited_ms: Date.now() - start,
          });
          return btn;
        }
      }
      await new Promise((r) => setTimeout(r, step));
    }
    _arenaDiagPushEvent({
      kind: 'submit_late_missing',
      adapter: adapter?.name || '',
      waited_ms: cap,
    });
    return null;
  }

  window._arenaDiagPushEvent = _arenaDiagPushEvent;
  window.arenaDiagRecentEvents = () => _arenaDiagEvents.slice();
  window._arenaDiagEvents = _arenaDiagEvents;   // read-only view for content.js
  window.arenaWaitForSubmit = arenaWaitForSubmit;
})();
