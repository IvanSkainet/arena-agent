"""Node-based sanity check for the Proposals tab loader.

Renders the table against realistic proposal shapes lifted from
the live v4.19.0 ledger (see the v4.20.0 dogfood), proves the
row-expand toggle works, the submit form validates required
fields, and error paths update the meta line without crashing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_JS = _REPO / "dashboard" / "assets" / "19-proposals.js"

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
  constructor(id, tag) {
    this.id = id;
    this._tag = (tag || "DIV").toUpperCase();
    this._cls = new Set();
    this._children = [];
    this._listeners = {};
    this._value = "";
    this._checked = false;
    this.textContent = "";
    this.innerHTML = "";
    this._style = {display: ""};
    this.disabled = false;
    this.dataset = {};
    this.colSpan = 0;
    const self = this;
    Object.defineProperty(this, "classList", {
      value: {
        add: (c) => self._cls.add(c),
        remove: (c) => self._cls.delete(c),
        toggle: (c) => { if (self._cls.has(c)) self._cls.delete(c);
                         else self._cls.add(c); },
        contains: (c) => self._cls.has(c),
        toString: () => Array.from(self._cls).join(" "),
      },
    });
    Object.defineProperty(this, "style", { get: () => self._style });
    Object.defineProperty(this, "className", {
      get: () => Array.from(self._cls).join(" "),
      set: (v) => { self._cls = new Set(String(v).split(/\s+/).filter(Boolean)); },
    });
    Object.defineProperty(this, "checked", {
      get: () => self._checked, set: (v) => { self._checked = !!v; },
    });
    Object.defineProperty(this, "value", {
      get: () => self._value, set: (v) => { self._value = String(v); },
    });
    Object.defineProperty(this, "offsetWidth", { get: () => 42 });
    Object.defineProperty(this, "tagName", { get: () => self._tag });
  }
  appendChild(c) { this._children.push(c); c._parent = this; return c; }
  addEventListener(name, fn) {
    (this._listeners[name] = this._listeners[name] || []).push(fn);
  }
  fire(name) { (this._listeners[name] || []).forEach(fn => fn.call(this)); }
}

const _els = {};
function _mk(id, tag) { _els[id] = _els[id] || new El(id, tag); return _els[id]; }
["proposalsAuto","proposalsInterval","proposalsRefreshDot",
 "proposalsMeta","proposalsTable","proposalsTbody","proposalsEmpty",
 "proposalsForm","prTitle","prRationale","prDiff","prFormResult",
 "prSubmitBtn","prSubmitToggle"].forEach(id => _mk(id));

globalThis.document = {
  getElementById: (id) => _els[id] || null,
  createElement: (tag) => new El("_" + tag, tag),
  readyState: "complete",
  addEventListener: () => {},
};
globalThis.window = globalThis;
globalThis.performance = { now: () => Date.now() };

// api() stub with settable payload / error mode.
let _apiPath = null;
let _apiOpts = null;
let _apiPayload = {ok: true, proposals: []};
let _apiMode = "ok";
globalThis.api = async (path, opts) => {
  _apiPath = path;
  _apiOpts = opts;
  if (_apiMode === "throw") throw new Error("network-down");
  return _apiPayload;
};
globalThis.copyToClipboard = () => {};
globalThis.__setPayload = (p) => { _apiPayload = p; };
globalThis.__setMode = (m) => { _apiMode = m; };
globalThis.__lastApi = () => ({ path: _apiPath, opts: _apiOpts });
globalThis.__els = _els;
"""


def _load() -> str:
    return _JS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# render table
# ---------------------------------------------------------------------------
_SAMPLE_LIST = {
    "ok": True,
    "count": 2,
    "proposals": [
        {
            "request_id": "0b7f2bd15f9447a5882dad5e5e99d5fe",
            "title": "v4.20.0 smoke",
            "rationale": "Trivial diff to prove pipeline",
            "state": "passed",
            "branch": "proposal/0b7f2bd1",
            "diff_bytes": 299,
            "diff_sha256": "ea46882c4597b361e81bd29feb64a31cda3cf2857dfd596c965477404fa9359f",
            "exit_code": 0,
            "tests_tail": "1500 passed",
            "submitted_at_iso": "2026-07-16T19:16:46Z",
            "updated_at_iso": "2026-07-16T19:17:35Z",
            "push_url": None,
            "client": "127.0.0.1",
        },
        {
            "request_id": "ec5c49413e8b446eb9321b4d20138ad8",
            "title": "smoke: hello file",
            "rationale": "v4.19.0 live smoke",
            "state": "failed",
            "branch": "proposal/ec5c4941",
            "diff_bytes": 222,
            "diff_sha256": "31fd88d4",
            "exit_code": 1,
            "tests_tail": "No module named pytest",
            "submitted_at_iso": "2026-07-16T17:34:55Z",
            "updated_at_iso": "2026-07-16T17:34:55Z",
            "push_url": None,
            "client": "127.0.0.1",
        },
    ],
}


def test_load_renders_table_rows_and_state_counts():
    harness = _DOM_STUB + f"__setPayload({json.dumps(_SAMPLE_LIST)});\n" + _load() + r"""
;(async () => {
  await window.loadProposals();
  const tb = __els.proposalsTbody;
  const meta = __els.proposalsMeta.innerHTML;
  console.log(JSON.stringify({
    rowsRendered: tb._children.length,
    metaHasTotal: meta.indexOf("Total 2") >= 0,
    metaHasPassedChip: meta.indexOf("1 passed") >= 0,
    metaHasFailedChip: meta.indexOf("1 failed") >= 0,
    metaHasManual: meta.indexOf("manual") >= 0,
  }));
})();
"""
    out = _run_node(harness)
    # 2 proposals = 2 mainRow + 2 detailRow = 4 rows.
    assert out["rowsRendered"] == 4
    assert out["metaHasTotal"] is True
    assert out["metaHasPassedChip"] is True
    assert out["metaHasFailedChip"] is True
    assert out["metaHasManual"] is True


def test_empty_list_shows_placeholder():
    harness = _DOM_STUB + "__setPayload({ok:true, proposals:[]});" + _load() + r"""
;(async () => {
  await window.loadProposals();
  const tb = __els.proposalsTbody;
  const firstCell = tb._children[0]._children[0];
  console.log(JSON.stringify({
    rows: tb._children.length,
    placeholderText: firstCell.textContent,
    placeholderClass: firstCell.className,
  }));
})();
"""
    out = _run_node(harness)
    assert out["rows"] == 1
    assert "No proposals yet" in out["placeholderText"]
    assert "pr-empty" in out["placeholderClass"]


def test_fetch_error_updates_meta_and_pulses_dot():
    harness = _DOM_STUB + '__setMode("throw");\n' + _load() + r"""
;(async () => {
  await window.loadProposals();
  const st = window.__proposalsTab.getState();
  console.log(JSON.stringify({
    lastError: st.lastError,
    dotClasses: Array.from(__els.proposalsRefreshDot._cls).join(","),
    metaMentionsError: __els.proposalsMeta.innerHTML.indexOf("network-down") >= 0,
  }));
})();
"""
    out = _run_node(harness)
    assert "network-down" in (out["lastError"] or "")
    assert "err" in out["dotClasses"]
    assert out["metaMentionsError"] is True


# ---------------------------------------------------------------------------
# submit form
# ---------------------------------------------------------------------------
def test_submit_missing_title_reports_error():
    harness = _DOM_STUB + _load() + r"""
;(async () => {
  __els.prTitle.value = "";
  __els.prDiff.value = "diff --git a/x b/x\n";
  await window.submitProposal();
  console.log(JSON.stringify({
    resultText: __els.prFormResult.textContent,
    resultClass: __els.prFormResult.className,
  }));
})();
"""
    out = _run_node(harness)
    assert "Title required" in out["resultText"]
    assert "err" in out["resultClass"]


def test_submit_missing_diff_reports_error():
    harness = _DOM_STUB + _load() + r"""
;(async () => {
  __els.prTitle.value = "some title";
  __els.prDiff.value = "";
  await window.submitProposal();
  console.log(JSON.stringify({
    resultText: __els.prFormResult.textContent,
    resultClass: __els.prFormResult.className,
  }));
})();
"""
    out = _run_node(harness)
    assert "Diff cannot be empty" in out["resultText"]
    assert "err" in out["resultClass"]


def test_submit_success_posts_json_and_reloads():
    harness = _DOM_STUB + r"""
// Toggle responses: first the submit succeeds, then loadProposals list is empty.
let _seq = 0;
const _r1 = {ok: true, request_id: "aabbccdd11223344"};
const _r2 = {ok: true, proposals: [
  {request_id:"aabbccdd11223344", title:"new", state:"pending",
   branch:"proposal/aabbccdd", diff_bytes:100, diff_sha256:"aa",
   submitted_at_iso:"2026-07-17T00:00:00Z", updated_at_iso:"2026-07-17T00:00:00Z"}
]};
globalThis.api = async (path, opts) => {
  _seq++;
  if (path.indexOf("submit") >= 0) return _r1;
  return _r2;
};
""" + _load() + r"""
;(async () => {
  __els.prTitle.value = "new proposal";
  __els.prRationale.value = "why";
  __els.prDiff.value = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-a\n+b\n";
  await window.submitProposal();
  // Give the loadProposals microtask a tick.
  await new Promise(r => setTimeout(r, 5));
  console.log(JSON.stringify({
    resultClass: __els.prFormResult.className,
    resultMentionsId: __els.prFormResult.textContent.indexOf("aabbccdd11223344") >= 0,
    titleCleared: __els.prTitle.value === "",
    diffCleared: __els.prDiff.value === "",
    tableRowCount: __els.proposalsTbody._children.length,
  }));
})();
"""
    out = _run_node(harness)
    assert "ok" in out["resultClass"]
    assert out["resultMentionsId"] is True
    assert out["titleCleared"] is True
    assert out["diffCleared"] is True
    # 1 proposal = 2 rows (main + detail).
    assert out["tableRowCount"] == 2


def test_submit_bridge_rejection_reports_reason():
    harness = _DOM_STUB + r"""
globalThis.api = async () => ({ok: false, error: "diff mentions .env"});
""" + _load() + r"""
;(async () => {
  __els.prTitle.value = "bad";
  __els.prDiff.value = "diff --git\n";
  await window.submitProposal();
  console.log(JSON.stringify({
    resultClass: __els.prFormResult.className,
    resultText: __els.prFormResult.textContent,
  }));
})();
"""
    out = _run_node(harness)
    assert "err" in out["resultClass"]
    assert ".env" in out["resultText"]


# ---------------------------------------------------------------------------
# auto-refresh timer
# ---------------------------------------------------------------------------
def test_auto_refresh_reads_interval_from_select():
    harness = _DOM_STUB + r"""
let _lastDelay = null;
const _origSI = globalThis.setInterval;
globalThis.setInterval = (fn, d) => { _lastDelay = d; return _origSI(fn, d); };
""" + _load() + r"""
;(async () => {
  __els.proposalsInterval.value = "3";
  __els.proposalsAuto.checked = true;
  __els.proposalsAuto.fire("change");
  console.log(JSON.stringify({lastDelay: _lastDelay}));
  clearInterval();
  process.exit(0);
})();
"""
    out = _run_node(harness)
    assert out["lastDelay"] == 3000


def test_form_toggle_flips_visibility_class():
    harness = _DOM_STUB + _load() + r"""
;(async () => {
  const before = __els.proposalsForm._cls.has("on");
  window.toggleProposalForm();
  const after1 = __els.proposalsForm._cls.has("on");
  window.toggleProposalForm();
  const after2 = __els.proposalsForm._cls.has("on");
  console.log(JSON.stringify({before, after1, after2}));
})();
"""
    out = _run_node(harness)
    assert out["before"] is False
    assert out["after1"] is True
    assert out["after2"] is False


def test_html_escape_prevents_injection():
    """Malicious title injection must be escaped in the rendered
    HTML -- otherwise a rogue proposal could inject <script>."""
    evil = {
        "ok": True,
        "proposals": [{
            "request_id": "1234567890abcdef",
            "title": "<script>alert(1)</script>",
            "state": "pending",
            "branch": "proposal/12345678",
            "rationale": "<img src=x onerror=alert(2)>",
            "diff_bytes": 0, "diff_sha256": "",
            "submitted_at_iso": "2026-07-17T00:00:00Z",
            "updated_at_iso": "2026-07-17T00:00:00Z",
        }],
    }
    harness = _DOM_STUB + f"__setPayload({json.dumps(evil)});" + _load() + r"""
;(async () => {
  await window.loadProposals();
  const rowHtml = __els.proposalsTbody._children[0].innerHTML;
  const detailHtml = __els.proposalsTbody._children[1]._children[0].innerHTML;
  console.log(JSON.stringify({
    rowEscaped: rowHtml.indexOf("<script>") === -1,
    rowHasEscapedLt: rowHtml.indexOf("&lt;script&gt;") >= 0,
    detailEscaped: detailHtml.indexOf("<img src=x") === -1,
    detailHasEscapedLt: detailHtml.indexOf("&lt;img") >= 0,
  }));
})();
"""
    out = _run_node(harness)
    assert out["rowEscaped"] is True
    assert out["rowHasEscapedLt"] is True
    assert out["detailEscaped"] is True
    assert out["detailHasEscapedLt"] is True
