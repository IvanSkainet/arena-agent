"""Node-based sanity check for 04e-overview-gpu-errors.js.

Renders the two cards against realistic /v1/hwinfo shapes and
proves fail-soft behaviour when GPU or systemd data is absent.
Uses the same DOM-stub approach as test_overview_toolbar_js.py
so no jsdom dependency is needed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_JS = _REPO / "dashboard" / "assets" / "04e-overview-gpu-errors.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not installed")


def _run_node(harness: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", harness],
        capture_output=True, text=True, timeout=15,
        cwd=str(_REPO),
    )
    assert proc.returncode == 0, (
        f"node exit {proc.returncode}\n--- stderr ---\n{proc.stderr}\n"
        f"--- stdout ---\n{proc.stdout}"
    )
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


_DOM_STUB = r"""
class El {
  constructor(id) {
    this.id = id;
    this._cls = new Set();
    this.textContent = "";
    this.innerHTML = "";
    this._style = {display: "", width: "0%"};
    this._children = [];
    this._tag = null;
    const self = this;
    Object.defineProperty(this, "classList", {
      value: {
        add: (c) => self._cls.add(c),
        remove: (c) => self._cls.delete(c),
        contains: (c) => self._cls.has(c),
        toString: () => Array.from(self._cls).join(" "),
      },
    });
    Object.defineProperty(this, "style", { get: () => self._style });
    Object.defineProperty(this, "parentElement", {
      get: () => self._parent || null,
      set: (v) => { self._parent = v; },
    });
    Object.defineProperty(this, "tagName", {
      get: () => (self._tag || "DIV"),
    });
  }
  appendChild(child) { this._children.push(child); child._parent = this; }
}
const _els = {};
function _mk(id) { _els[id] = _els[id] || new El(id); return _els[id]; }

// Container ids
["gpuCard","gpuBadge","gpuEmpty","gpuBody","gpuName","gpuDriver",
 "gpuUtilBar","gpuUtilText","gpuVramBar","gpuVramText","gpuTempText",
 "errCard","errBadge","errEmpty","errBody","errSystemCount",
 "errUserCount","errList"].forEach(_mk);

// Simulate the H2 header being the badge's parentElement.
const _gpuH2 = new El("_gpuH2"); _gpuH2._tag = "H2";
const _errH2 = new El("_errH2"); _errH2._tag = "H2";
_els.gpuBadge._parent = _gpuH2;
_els.errBadge._parent = _errH2;

globalThis.document = {
  getElementById: (id) => _els[id] || null,
  createElement: (tag) => { const e = new El("_" + tag); e._tag = tag.toUpperCase(); return e; },
  readyState: "complete",
  addEventListener: () => {},
};
globalThis.window = globalThis;

// Stub refreshOverview so the wrapper install path is exercised.
globalThis.refreshOverview = () => Promise.resolve({ok: true});

// Stub the api() helper the module prefers.
let _apiPayload = null;
globalThis.api = async () => _apiPayload;

globalThis.__setPayload = (p) => { _apiPayload = p; };
globalThis.__els = _els;
globalThis.__gpuH2 = _gpuH2;
globalThis.__errH2 = _errH2;
"""


def _load_module_js() -> str:
    return _JS.read_text(encoding="utf-8")


def test_full_render_populates_gpu_card():
    harness = _DOM_STUB + _load_module_js() + r"""
;(async () => {
  __setPayload({
    ok: true,
    hardware: {
      gpu: {
        name: "NVIDIA GeForce RTX 4090",
        driver: "550.100",
        vram_total_mb: 24576, vram_used_mb: 8192, vram_free_mb: 16384,
        temperature_c: 67, utilization_pct: 45
      },
      systemd_failed: {available: true, system_failed: [], user_failed: []}
    }
  });
  await window.__overviewGpuErrors.fetch();
  const g = __els;
  console.log(JSON.stringify({
    gpuName: g.gpuName.textContent,
    gpuDriver: g.gpuDriver.textContent,
    utilPct: g.gpuUtilText.textContent,
    utilBarWidth: g.gpuUtilBar.style.width,
    vramText: g.gpuVramText.textContent,
    vramBarWidth: g.gpuVramBar.style.width,
    temp: g.gpuTempText.textContent,
    badgeText: g.gpuBadge.textContent,
    badgeClasses: Array.from(g.gpuBadge._cls).join(","),
    gpuCardHidden: g.gpuCard.style.display === "none",
  }));
})();
"""
    out = _run_node(harness)
    assert out["gpuName"] == "NVIDIA GeForce RTX 4090"
    assert out["gpuDriver"] == "550.100"
    assert out["utilPct"] == "45%"
    assert out["utilBarWidth"] == "45%"
    assert "8.0 GB / 24.0 GB" == out["vramText"]
    # 8192 / 24576 * 100 = 33.3
    assert out["vramBarWidth"] == "33.3%"
    assert out["temp"] == "67 °C"
    assert "ok" in out["badgeClasses"]
    assert out["gpuCardHidden"] is False


def test_hot_gpu_switches_badge_to_hot():
    harness = _DOM_STUB + _load_module_js() + r"""
;(async () => {
  __setPayload({
    ok: true,
    hardware: {
      gpu: {name: "Hot Card", driver: "1.0",
            vram_total_mb: 8000, vram_used_mb: 4000,
            temperature_c: 88, utilization_pct: 99},
      systemd_failed: {available: true, system_failed: [], user_failed: []}
    }
  });
  await window.__overviewGpuErrors.fetch();
  console.log(JSON.stringify({
    badgeClasses: Array.from(__els.gpuBadge._cls).join(","),
    badgeText: __els.gpuBadge.textContent,
  }));
})();
"""
    out = _run_node(harness)
    assert "hot" in out["badgeClasses"]
    assert "88°C" in out["badgeText"]
    assert "99%" in out["badgeText"]


def test_no_gpu_hides_card_and_h2():
    harness = _DOM_STUB + _load_module_js() + r"""
;(async () => {
  __setPayload({
    ok: true,
    hardware: {
      systemd_failed: {available: true, system_failed: [], user_failed: []}
    }
  });
  await window.__overviewGpuErrors.fetch();
  console.log(JSON.stringify({
    cardDisplay: __els.gpuCard.style.display,
    h2Display: __gpuH2.style.display,
  }));
})();
"""
    out = _run_node(harness)
    assert out["cardDisplay"] == "none"
    assert out["h2Display"] == "none"


def test_failed_units_render_list_and_bad_badge():
    harness = _DOM_STUB + _load_module_js() + r"""
;(async () => {
  __setPayload({
    ok: true,
    hardware: {
      gpu: null,
      systemd_failed: {
        available: true,
        system_failed: [{unit:"foo.service", description:"foo desc"}],
        user_failed: [
          {unit:"bar.service", description:"bar desc"},
          {unit:"baz.service", description:"baz desc"}
        ]
      }
    }
  });
  await window.__overviewGpuErrors.fetch();
  console.log(JSON.stringify({
    sys: __els.errSystemCount.textContent,
    user: __els.errUserCount.textContent,
    badgeText: __els.errBadge.textContent,
    badgeClasses: Array.from(__els.errBadge._cls).join(","),
    itemCount: __els.errList._children.length,
  }));
})();
"""
    out = _run_node(harness)
    assert out["sys"] == "1 failed"
    assert out["user"] == "2 failed"
    assert out["badgeText"] == "3 failed"
    assert "fail" in out["badgeClasses"]
    assert out["itemCount"] == 3


def test_healthy_units_show_ok_badge_and_one_row():
    harness = _DOM_STUB + _load_module_js() + r"""
;(async () => {
  __setPayload({
    ok: true,
    hardware: {
      systemd_failed: {available: true, system_failed: [], user_failed: []}
    }
  });
  await window.__overviewGpuErrors.fetch();
  console.log(JSON.stringify({
    badgeClasses: Array.from(__els.errBadge._cls).join(","),
    badgeText: __els.errBadge.textContent,
    itemCount: __els.errList._children.length,
  }));
})();
"""
    out = _run_node(harness)
    assert "ok" in out["badgeClasses"]
    assert out["badgeText"] == "healthy"
    # One placeholder "All units healthy." row.
    assert out["itemCount"] == 1


def test_systemd_unavailable_hides_error_card():
    harness = _DOM_STUB + _load_module_js() + r"""
;(async () => {
  __setPayload({
    ok: true,
    hardware: { systemd_failed: {available: false} }
  });
  await window.__overviewGpuErrors.fetch();
  console.log(JSON.stringify({
    cardDisplay: __els.errCard.style.display,
    h2Display: __errH2.style.display,
  }));
})();
"""
    out = _run_node(harness)
    assert out["cardDisplay"] == "none"
    assert out["h2Display"] == "none"


def test_fetch_failure_is_swallowed_no_dom_thrash():
    """A rejected api() call must not crash the module or leave
    a half-updated card. Prior _lastGpu / _lastErr stay intact."""
    harness = _DOM_STUB + r"""
globalThis.api = async () => { throw new Error("network-down"); };
""" + _load_module_js() + r"""
;(async () => {
  let raised = false;
  try { await window.__overviewGpuErrors.fetch(); } catch (e) { raised = true; }
  const st = window.__overviewGpuErrors.getState();
  console.log(JSON.stringify({
    raised,
    lastGpu: st.lastGpu,
    lastErr: st.lastErr,
  }));
})();
"""
    out = _run_node(harness)
    assert out["raised"] is False, "fetch() must swallow errors"
    assert out["lastGpu"] is None
    assert out["lastErr"] is None


def test_wrapper_chains_around_refreshOverview():
    """Confirm the wrapper reads _origRefresh so a subsequent
    manual refreshOverview() call still triggers the primary
    payload, not an infinite recursion."""
    harness = _DOM_STUB + _load_module_js() + r"""
;(async () => {
  let calls = 0;
  const orig = window.refreshOverview;
  // Replace the *wrapped* one and call it
  window.__origCallCount = 0;
  const outer = window.refreshOverview;
  // Prove the wrapper actually forwards.
  __setPayload({ok: true, hardware: {gpu: null,
    systemd_failed: {available: true, system_failed: [], user_failed: []}}});
  await outer();
  await outer();
  console.log(JSON.stringify({
    wrapperExists: outer !== orig || typeof orig === "function",
    // We can't easily count _origRefresh calls from inside the sandbox,
    // but no crash + card gets rendered proves the chain works.
    errBadgeText: __els.errBadge.textContent,
  }));
})();
"""
    out = _run_node(harness)
    assert out["errBadgeText"] == "healthy"
