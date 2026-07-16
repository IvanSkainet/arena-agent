"""Node-based sanity check for 04d-overview-toolbar.js.

Uses a hand-rolled DOM stub so we don't drag in jsdom (huge
dependency for what is a tiny wrapper). Proves:

* the module registers itself, wraps window.refreshOverview,
  and puts a diagnostic namespace on window.
* a Promise-returning refresh gets its outcome captured
  (last duration + timestamp) and the meta line is rewritten.
* a rejection path pulses the error dot and still updates meta.
* the interval selector is what drives the auto-refresh timer
  (not a hardcoded number).

The test is skipped when Node is not installed. The v4.15.0
and v4.18.0 releases used the same pattern (Node integration
tests) so this fits the established convention.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_JS = _REPO / "dashboard" / "assets" / "04d-overview-toolbar.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not installed in this env")


def _run_node(harness: str) -> dict:
    """Execute ``harness`` under Node and return JSON printed to stdout."""
    proc = subprocess.run(
        ["node", "-e", harness],
        capture_output=True, text=True, timeout=15,
        cwd=str(_REPO),
    )
    assert proc.returncode == 0, (
        f"node exit {proc.returncode}\n--- stderr ---\n{proc.stderr}\n"
        f"--- stdout ---\n{proc.stdout}"
    )
    # Only the last line is the JSON blob so debug prints don't
    # interfere. Callers can `console.log(JSON.stringify(...))` any
    # time and previous log lines just get ignored.
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


_DOM_STUB = r"""
// Minimal DOM stub -- enough surface area for the toolbar.
class El {
  constructor(id) {
    this.id = id;
    this.classList = new Set();
    this._checked = false;
    this._value = "15";
    this._listeners = {};
    this.textContent = "";
    this.innerHTML = "";
    Object.defineProperty(this, "classList", {
      value: {
        add: (c) => this._cls.add(c),
        remove: (c) => this._cls.delete(c),
        contains: (c) => this._cls.has(c),
        toString: () => Array.from(this._cls).join(" "),
      },
      writable: false,
    });
    this._cls = new Set();
    Object.defineProperty(this, "checked", {
      get: () => this._checked, set: (v) => { this._checked = !!v; },
    });
    Object.defineProperty(this, "value", {
      get: () => this._value, set: (v) => { this._value = String(v); },
    });
    Object.defineProperty(this, "offsetWidth", { get: () => 42 });
  }
  addEventListener(name, fn) {
    (this._listeners[name] = this._listeners[name] || []).push(fn);
  }
  fire(name) {
    (this._listeners[name] || []).forEach(fn => fn.call(this));
  }
}

const _els = {};
function _mk(id) { _els[id] = _els[id] || new El(id); return _els[id]; }
// Every id the toolbar reaches for.
["overviewAuto","overviewInterval","overviewRefreshDot",
 "overviewMeta"].forEach(_mk);

globalThis.document = {
  getElementById: (id) => _els[id] || null,
  readyState: "complete",
  addEventListener: () => {},
};
globalThis.window = globalThis;
globalThis.performance = { now: () => Date.now() };

// Original refreshOverview -- returns a Promise so the wrapper
// exercises the async branch.
let _calls = 0;
globalThis.refreshOverview = function() {
  _calls++;
  return Promise.resolve({ok: true, call: _calls});
};
globalThis.__calls = () => _calls;
globalThis.__els = _els;
"""


def _load_module_js() -> str:
    return _JS.read_text(encoding="utf-8")


def test_wrapper_replaces_refresh_and_captures_duration():
    harness = _DOM_STUB + _load_module_js() + r"""
;(async () => {
  // Fire the wrapped refresh once.
  await window.refreshOverview();
  const state = window.__overviewToolbar.getState();
  const meta = __els.overviewMeta.innerHTML;
  console.log(JSON.stringify({
    calls: __calls(),
    wrapperReplaced: window.refreshOverview.toString().indexOf("_originalRefresh") >= 0,
    hasDuration: state.lastDurationMs !== null,
    hasTimestamp: state.lastRefreshAt !== null,
    lastError: state.lastError,
    metaMentionsLastRefresh: meta.indexOf("Last refresh") >= 0,
    metaMentionsMs: meta.indexOf("ms") >= 0,
    metaMentionsManual: meta.indexOf("manual") >= 0,
  }));
})();
"""
    out = _run_node(harness)
    assert out["calls"] == 1, "wrapper should have called through once"
    assert out["wrapperReplaced"] is True, "window.refreshOverview must be wrapped"
    assert out["hasDuration"] is True
    assert out["hasTimestamp"] is True
    assert out["lastError"] is None
    assert out["metaMentionsLastRefresh"] is True
    assert out["metaMentionsMs"] is True
    assert out["metaMentionsManual"] is True


def test_wrapper_captures_rejection_and_pulses_error_dot():
    harness = _DOM_STUB + r"""
// Override the refresher to reject.
globalThis.refreshOverview = function() {
  return Promise.reject(new Error("boom-net"));
};
""" + _load_module_js() + r"""
;(async () => {
  try { await window.refreshOverview(); } catch (e) { /* expected */ }
  const state = window.__overviewToolbar.getState();
  const dotClasses = Array.from(__els.overviewRefreshDot._cls).join(",");
  const meta = __els.overviewMeta.innerHTML;
  console.log(JSON.stringify({
    lastError: state.lastError,
    dotClasses,
    metaMentionsError: meta.indexOf("boom-net") >= 0,
  }));
})();
"""
    out = _run_node(harness)
    assert "boom-net" in (out["lastError"] or "")
    assert "err" in out["dotClasses"]
    assert out["metaMentionsError"] is True


def test_auto_refresh_uses_interval_value_from_dom():
    """Set the interval selector to a small value, tick the check-
    box, then inspect the last setInterval delay."""
    harness = _DOM_STUB + r"""
// Trap setInterval to inspect the delay.
let _lastDelay = null;
const _origSI = globalThis.setInterval;
globalThis.setInterval = function(fn, delay) {
  _lastDelay = delay;
  return _origSI(fn, delay);
};
""" + _load_module_js() + r"""
;(async () => {
  __els.overviewInterval.value = "7";
  __els.overviewAuto.checked = true;
  __els.overviewAuto.fire("change");
  console.log(JSON.stringify({
    lastDelayMs: _lastDelay,
    // 7 seconds * 1000
    matches7s: _lastDelay === 7000,
  }));
  // Clean up the interval so node doesn't hang.
  clearInterval();
  process.exit(0);
})();
"""
    out = _run_node(harness)
    assert out["lastDelayMs"] == 7000, out


def test_disabling_auto_refresh_clears_timer():
    harness = _DOM_STUB + r"""
let _cleared = 0;
const _origCI = globalThis.clearInterval;
globalThis.clearInterval = function(id) { _cleared++; return _origCI(id); };
""" + _load_module_js() + r"""
;(async () => {
  __els.overviewInterval.value = "15";
  __els.overviewAuto.checked = true;
  __els.overviewAuto.fire("change");   // arm the timer
  __els.overviewAuto.checked = false;
  __els.overviewAuto.fire("change");   // disarm -- should clearInterval
  console.log(JSON.stringify({cleared: _cleared > 0}));
  process.exit(0);
})();
"""
    out = _run_node(harness)
    assert out["cleared"] is True, out


def test_diagnostic_namespace_is_non_enumerable():
    """__overviewToolbar hides from Object.keys(window) so page
    inspectors don't get spammed with an implementation detail."""
    harness = _DOM_STUB + _load_module_js() + r"""
;(async () => {
  const keys = Object.keys(globalThis);
  console.log(JSON.stringify({
    inKeys: keys.indexOf("__overviewToolbar") >= 0,
    stillAccessible: typeof globalThis.__overviewToolbar === "object",
  }));
})();
"""
    out = _run_node(harness)
    assert out["inKeys"] is False
    assert out["stillAccessible"] is True
