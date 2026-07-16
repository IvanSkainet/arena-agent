"""Tests for the Audit-tab client-side ring buffer cap (v4.12.0).

A long-running live-tail session (v4.10.0) used to grow
``__auditState.raw`` unbounded -- a Dashboard left open for hours
could accumulate tens of thousands of rows in memory. v4.12.0
caps the buffer at ``__AUDIT_RING_CAP`` and drops the oldest
entries when it overflows, tracking the running total of dropped
rows in ``__auditState.evicted`` for the meta line.

These are static checks against the JS bundle (same shape as the
other Audit-tab guard tests). No headless browser required.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_JS = _REPO / "dashboard" / "assets" / "16-audit.js"
_CSS = _REPO / "dashboard" / "assets" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Constant + helper
# ---------------------------------------------------------------------------
def test_ring_cap_constant_defined_and_reasonable():
    """The cap must be defined at module scope so a reader can find
    the number in one place, and must be within a sane range (too
    small = churn, too large = OOM defeats the purpose)."""
    js = _read(_JS)
    assert "__AUDIT_RING_CAP" in js
    # Grab the literal via a regex; fail if the constant is
    # accidentally computed at runtime (harder to audit).
    import re
    m = re.search(r"const\s+__AUDIT_RING_CAP\s*=\s*(\d+)\s*;", js)
    assert m, "__AUDIT_RING_CAP must be a literal integer constant"
    cap = int(m.group(1))
    assert 500 <= cap <= 50_000, (
        f"__AUDIT_RING_CAP={cap} outside sane range 500..50000. "
        "Too small churns filter/pagination; too large defeats the "
        "point of a cap."
    )


def test_ring_cap_helper_exists_and_returns_count():
    """The helper must be a standalone function so tests can pin
    its exact behaviour without spinning up a live-tail session."""
    js = _read(_JS)
    assert "function __auditEnforceRingCap(" in js
    # Contract: returns the number of rows dropped so callers can
    # bump the eviction counter. Guard against a future edit that
    # accidentally makes it side-effect only.
    assert "return over" in js or "return 0" in js


def test_ring_cap_helper_drops_from_head_not_tail():
    """Newest events sit at the tail (push). Trimming to keep the
    latest window means dropping the head via splice(0, over).
    Regression guard against a future edit that accidentally uses
    ``.pop()`` or ``splice(-over)``, which would drop the events
    the operator actually wants to see."""
    js = _read(_JS)
    assert "splice(0" in js, (
        "ring-cap trim must drop from the head via splice(0, N); "
        "any pop()/splice(-N) would drop the newest events instead"
    )


def test_state_object_declares_evicted_counter():
    js = _read(_JS)
    assert "evicted:" in js
    # Counter must be a Number so += works; look for the literal 0.
    assert "evicted: 0" in js


# ---------------------------------------------------------------------------
# Integration points
# ---------------------------------------------------------------------------
def test_live_tail_ingest_calls_ring_cap():
    """Every push into __auditState.raw during a live-tail session
    must run the cap enforcement immediately after; otherwise a
    fast source (thousands of events in a burst) could still grow
    the buffer before the next tab-render evaluates cap."""
    js = _read(_JS)
    # Locate the __auditIngestLiveEvent function and check it
    # calls __auditEnforceRingCap AFTER the .push()s.
    start = js.find("function __auditIngestLiveEvent(")
    assert start != -1, "__auditIngestLiveEvent function missing"
    end = js.find("\nfunction ", start + 1)
    if end == -1:
        end = js.find("\nasync function ", start + 1)
    if end == -1:
        end = len(js)
    body = js[start:end]
    push_pos = body.find(".push")
    cap_pos = body.find("__auditEnforceRingCap")
    assert push_pos != -1, "ingest must .push() the event"
    assert cap_pos != -1, "ingest must call __auditEnforceRingCap()"
    assert cap_pos > push_pos, (
        "__auditEnforceRingCap must run AFTER the .push() -- "
        "otherwise a burst of events grows the buffer past cap "
        "before the trim runs"
    )
    # And the return value must be added to state.evicted.
    assert "__auditState.evicted +=" in body, (
        "ingest must accumulate the drop count into "
        "__auditState.evicted for the meta line"
    )


def test_load_audit_reload_resets_evicted_counter():
    """A fresh /v1/audit fetch replaces the buffer entirely, so
    the eviction counter should also reset. Otherwise the meta
    line would show a stale total from a previous live-tail
    session that no longer relates to what's on screen."""
    js = _read(_JS)
    # Find the loadAudit function and verify the assignment to
    # raw is followed by an evicted reset.
    start = js.find("async function loadAudit(")
    assert start != -1
    body = js[start:start + 4000]  # generous slice
    raw_assign = body.find("__auditState.raw = result.events")
    assert raw_assign != -1
    # The very next mutation on __auditState.evicted must be an
    # assignment (either 0 or __auditEnforceRingCap()) so the
    # meta line matches the fresh buffer.
    tail = body[raw_assign:raw_assign + 400]
    assert "__auditState.evicted =" in tail, (
        "loadAudit must reset __auditState.evicted after replacing "
        "the buffer -- meta line would otherwise show a stale total"
    )


def test_meta_line_conditionally_shows_evicted_counter():
    """The counter must be shown only when > 0 so the meta line
    stays uncluttered during typical sessions. Verifies both the
    guard and the visible label text."""
    js = _read(_JS)
    # Guard: shown only when > 0.
    assert "__auditState.evicted > 0" in js
    # Label text: something a human recognises. Being strict on
    # the exact word so translation drift is a deliberate call.
    assert '"evicted "' in js


# ---------------------------------------------------------------------------
# Containment (v4.0.x lesson still holds)
# ---------------------------------------------------------------------------
def test_dashboard_css_untouched_by_ring_cap_work():
    """Ring-cap is pure JS -- no CSS additions. Guard against a
    future edit that adds an "evicted N" pill with its own styles
    and forgets to scope them to #tab-audit."""
    css = _read(_CSS)
    # Nothing evicted-specific may leak into shared CSS.
    for token in ("evicted", "audit-ring", "AUDIT_RING"):
        assert token not in css, (
            f"leaked into dashboard.css: {token!r}"
        )
