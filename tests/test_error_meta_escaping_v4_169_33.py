"""v4.169.33: dashboard error meta line must never inject HTML.

The refresh-meta toolbar exists in four near-identical copies
(04d-overview, 08b-missions, 19-proposals, 20-transports). All four push
a ``last error: <message>`` fragment into ``innerHTML``. The message is
``String(e.message)`` from the wrapped loader, and the API helper
(02-api-helper.js) builds that message as::

    errMsg += ": " + j.error        # j.error is the SERVER-RETURNED string

so any endpoint whose error body reflects caller input (a missing
mission name, an invalid path) hands markup to the operator's browser.
The operator's browser is where the bridge bearer token lives, so this
is a token-theft chain if any tab's loader ever throws a server-shaped
error.

19-proposals.js and 20-transports.js escaped the fragment when written.
04d-overview-toolbar.js and 08b-missions-toolbar.js did not -- the copy
drifted, and CodeQL never flagged the two unescaped copies, which is
why this landed as a regression gate rather than an alert dismissal.

Tests here:

* a static ratchet over every dashboard asset: the literal
  ``"last error: " +`` must be followed by an escaping call;
* a behavioural Node harness that rejects the wrapped loader with a
  markup payload and proves the rendered meta line contains the escaped
  text and no live tag.

The behavioural part is skipped where Node is absent, matching the
convention from test_overview_toolbar_js.py.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._node_budget import node_timeout

_REPO = Path(__file__).resolve().parents[1]
_ASSETS = _REPO / "dashboard" / "assets"

_TOOLBARS = {
    "dashboard/assets/04d-overview-toolbar.js": {
        "ids": ["overviewAuto", "overviewInterval",
                "overviewRefreshDot", "overviewMeta"],
        "loader": "refreshOverview",
        "meta_id": "overviewMeta",
    },
    "dashboard/assets/08b-missions-toolbar.js": {
        "ids": ["missionsAuto", "missionsInterval",
                "missionsRefreshDot", "missionsMeta"],
        "loader": "loadMissions",
        "meta_id": "missionsMeta",
    },
}


# --- static ratchet ----------------------------------------------------------

def test_no_unescaped_last_error_reaches_innerhtml():
    # Pair each `"last error: " + ident` fragment with what the file does
    # with that array. Concatenations whose array only feeds `.title`
    # (04c-net-breaker.js tooltip) are text-safe and must stay silent --
    # a noisy detector is worse than none.
    innerhtml_arrays = re.compile(r'\.innerHTML\s*=\s*(\w+)\.map\(')
    frag_push = re.compile(r'\b(\w+)\.push\(\s*"last error:\s*"\s*\+\s*+(\w+)')
    offenders = []
    for js in sorted(_ASSETS.glob("*.js")):
        src = js.read_text(encoding="utf-8")
        sinks = set(innerhtml_arrays.findall(src))
        if not sinks:
            continue
        for lineno, line in enumerate(src.splitlines(), 1):
            m = frag_push.search(line)
            if m and m.group(1) in sinks:
                val = m.group(2)
                if val in ("esc", "_escape"):
                    continue  # fragment wrapped in an escaping call
                if not re.search(r'\+\s*+(?:esc|_escape)\(\s*' + re.escape(val), line):
                    offenders.append(f"{js.name}:{lineno}:{line.strip()[:80]}")
    assert not offenders, (
        "error text concatenated unescaped into an innerHTML-bound array:\n"
        + "\n".join(offenders))


def test_both_toolbars_reference_the_escape_on_the_meta_line():
    for rel in _TOOLBARS:
        src = (_REPO / rel).read_text(encoding="utf-8")
        assert "_escape(_lastError)" in src, f"{rel} lost the escape"


# --- behavioural proof --------------------------------------------------------

_MARKER = '<img src=x onerror=window.__xss=1>'


def _harness(rel: str, cfg: dict) -> str:
    ids = ", ".join(f'"{i}"' for i in cfg["ids"])
    src = (_REPO / rel).read_text(encoding="utf-8")
    payload = json.dumps(_MARKER)
    return r"""
class El {
  constructor(id) {
    this.id = id;
    this._cls = new Set();
    this._checked = false;
    this._value = "15";
    this._listeners = {};
    this.textContent = "";
    this.innerHTML = "";
    Object.defineProperty(this, "classList", { value: {
      add: (c) => this._cls.add(c),
      remove: (c) => this._cls.delete(c),
      contains: (c) => this._cls.has(c),
    }});
    Object.defineProperty(this, "checked",
      { get: () => this._checked, set: (v) => { this._checked = !!v; } });
    Object.defineProperty(this, "value",
      { get: () => this._value, set: (v) => { this._value = String(v); } });
    Object.defineProperty(this, "offsetWidth", { get: () => 42 });
  }
  addEventListener(n, fn) {
    (this._listeners[n] = this._listeners[n] || []).push(fn);
  }
}
const _els = {};
const _mk = (id) => { _els[id] = _els[id] || new El(id); return _els[id]; };
[IDS_HERE].forEach(_mk);
globalThis.document = {
  getElementById: (id) => _els[id] || null,
  readyState: "complete",
  addEventListener: () => {},
};
globalThis.window = globalThis;
globalThis.performance = { now: () => Date.now() };
globalThis.LOADER_HERE = function () {
  return Promise.reject(new Error(PAYLOAD_HERE));
};
MODULE_SRC_HERE
;(async () => {
  try { await window.LOADER_HERE(); } catch (e) { /* rejection drives the meta */ }
  const meta = _els[META_ID_HERE].innerHTML;
  console.log(JSON.stringify({ meta: meta, xssFired: !!globalThis.__xss }));
})();
""".replace("IDS_HERE", ids) \
        .replace("LOADER_HERE", cfg["loader"]) \
        .replace("PAYLOAD_HERE", payload) \
        .replace("MODULE_SRC_HERE", src) \
        .replace("META_ID_HERE", json.dumps(cfg["meta_id"]))


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node not installed in this env")
@pytest.mark.skipif(sys.platform == "win32",
                    reason="Node child-process harness times out on win32 "
                           "(same constraint as test_overview_toolbar_js)")
@pytest.mark.parametrize("rel", sorted(_TOOLBARS))
def test_meta_line_escapes_markup_payload(rel):
    proc = subprocess.run(
        ["node", "-e", _harness(rel, _TOOLBARS[rel])],
        capture_output=True, text=True, timeout=node_timeout(),
        cwd=str(_REPO),
    )
    assert proc.returncode == 0, (
        f"node exit {proc.returncode}\nstderr: {proc.stderr[:800]}")
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert _MARKER not in out["meta"], (
        f"raw markup reached innerHTML in {rel}: {out['meta'][:200]}")
    assert "&lt;img" in out["meta"], (
        f"escaped error text missing from meta in {rel}: {out['meta'][:200]}")
    assert out["xssFired"] is False
