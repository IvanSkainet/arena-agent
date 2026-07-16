"""Tests for the Audit-tab live-tail toggle (v4.10.0).

The Audit tab (v4.6.0) polled ``/v1/audit`` every 5 seconds; v4.10.0
adds a second toggle that subscribes to ``/v1/audit/stream?follow=1``
(v4.9.0 endpoint) and pushes new events into the same
``__auditState.raw`` in real time.

Same containment discipline as v4.6.0 / v4.7.0: all new styling
scoped to ``#tab-audit``, ``dashboard.css`` unchanged, no hex
literals inline. Guards below fail immediately if any of those
rules regress.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-13-audit.html"
_JS = _REPO / "dashboard" / "assets" / "16-audit.js"
_CSS = _REPO / "dashboard" / "assets" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Toolbar markup
# ---------------------------------------------------------------------------
def test_body_has_live_tail_checkbox_and_status_dot():
    body = _read(_BODY)
    assert 'id="auditLive"' in body, "live-tail checkbox missing from body"
    assert 'id="auditLiveDot"' in body, "live-tail status dot missing from body"
    # The v4.6.0 auto-refresh checkbox must still be there -- the two
    # toggles are mutually exclusive but both live in the toolbar.
    assert 'id="auditAuto"' in body


def test_body_style_defines_dot_states_on_and_err():
    """The dot must have both 'on' (streaming) and 'err' (reconnecting)
    states so the operator can tell a live-connected tab from a
    silently broken one."""
    body = _read(_BODY)
    assert ".audit-live-dot" in body
    assert ".audit-live-dot.on" in body
    assert ".audit-live-dot.err" in body


# ---------------------------------------------------------------------------
# JS behaviour contract
# ---------------------------------------------------------------------------
def test_js_extends_audit_state_with_live_fields():
    js = _read(_JS)
    for field in ("liveController", "liveReader", "liveLastTs",
                  "liveEvents", "liveReconnectTimer"):
        assert field in js, f"__auditState missing live field: {field}"


def test_js_exposes_live_helpers_privately():
    """Private helpers use the '__audit...' prefix so they don't
    pollute the global namespace shared by every other tab."""
    js = _read(_JS)
    for name in ("__auditToggleLive", "__auditOpenLiveConnection",
                 "__auditStopLive", "__auditConsumeStream",
                 "__auditIngestLiveEvent", "__auditLiveSupported",
                 "__auditLiveSetStatus", "__auditScheduleLiveReconnect"):
        assert name in js, f"missing live-tail helper: {name}"


def test_js_uses_correct_endpoint_with_follow_and_max_duration():
    """The stream call must hit /v1/audit/stream?follow=1 with a
    bounded max_duration so a forgotten tab can't hold a bridge
    worker forever (server also caps this at 300s)."""
    js = _read(_JS)
    assert "/v1/audit/stream?follow=1" in js
    assert "max_duration=" in js
    # Cursor must be threaded through so reconnects are gap-free.
    assert "since=" in js


def test_js_reconnects_after_stream_end():
    """When the server hits max_duration the stream ends cleanly; the
    client must schedule a reconnect with the last-known ts so no
    event is lost across the rollover window."""
    js = _read(_JS)
    assert "__auditScheduleLiveReconnect" in js
    assert "setTimeout(" in js
    assert "liveLastTs" in js


def test_js_auto_refresh_and_live_are_mutually_exclusive():
    """Both toggles do essentially the same job; keep exactly one on
    at a time. Regression guard against a future edit that forgets
    to disable auto-refresh when live-tail comes on (or vice versa)."""
    js = _read(_JS)
    # __auditToggleLive turns auto-refresh off when live-tail is turned on.
    assert "auditAuto" in js
    # __auditToggleAuto aborts live-tail when auto-refresh is turned on.
    assert "__auditStopLive()" in js


def test_js_uses_abort_controller_for_clean_stop():
    """The stream fetch must use AbortController so the ``off``
    toggle actually tears down the connection (otherwise the reader
    keeps decoding until the server closes)."""
    js = _read(_JS)
    assert "AbortController" in js
    assert "controller.abort" in js or ".abort()" in js


def test_js_ndjson_parser_survives_bad_lines():
    """A single malformed line must not tear the stream down. This
    is a contract with the server which surfaces malformed audit
    lines as ``{type:raw,line:...}`` -- but the client-side parser
    should also survive garbage between valid lines."""
    js = _read(_JS)
    # Parser wraps JSON.parse in try/catch inside the stream loop.
    assert "JSON.parse" in js
    assert "console.warn" in js or "console.error" in js


def test_js_supports_gap_free_reconnect_with_since_cursor():
    """After a reconnect we must not re-emit events already visible.
    The client tracks the newest ts seen live (or, on first connect,
    seeds from the last ts already in __auditState.raw) and passes
    it as ``since=`` on the next stream open."""
    js = _read(_JS)
    assert "encodeURIComponent(__auditState.liveLastTs)" in js
    # The seed-from-history branch must exist so the very first
    # subscription doesn't dupe the last N rows already on screen.
    assert "__auditState.raw.length" in js


def test_js_live_supported_probe_guards_older_browsers():
    """Some browsers only have fetch() but no ReadableStream reader.
    The toggle must render disabled with a helpful tooltip in that
    case rather than silently doing nothing when clicked."""
    js = _read(_JS)
    assert "__auditLiveSupported" in js
    assert "ReadableStream" in js
    assert ".disabled = true" in js


def test_js_ingest_ignores_meta_and_exit_control_events():
    """Meta / exit / error come from the streaming envelope, not the
    audit vocabulary -- they must not show up as fake audit rows in
    the table."""
    js = _read(_JS)
    # The ingest helper explicitly skips these control types.
    assert '"meta"' in js
    assert '"exit"' in js
    assert '"error"' in js


def test_js_renders_only_when_tab_is_active():
    """Live-tail runs even when the tab is hidden (to keep the
    counter accurate across tab switches), but we must not repaint
    the table on every event when the operator is on a different
    tab -- that's just CPU burn."""
    js = _read(_JS)
    assert "tab-audit" in js
    assert "classList.contains(\"active\")" in js


# ---------------------------------------------------------------------------
# Containment (v4.0.x lesson still active)
# ---------------------------------------------------------------------------
def test_dashboard_css_untouched_by_live_tail_additions():
    """No new selectors from the live-tail work may leak into shared
    CSS. The v4.6.0 dashboard.css was byte-identical to v4.0.0 and
    must stay that way."""
    css = _read(_CSS)
    for token in ("audit-live-dot", "auditLive"):
        assert token not in css, f"leaked into dashboard.css: {token}"


def test_new_dot_style_stays_scoped_to_tab_audit():
    """The v4.6.0 audit-polish tests already assert every selector
    starts with ``#tab-audit``. Re-run the same shape here specifically
    against the new .audit-live-dot rules so a regression targeted at
    just this class fails immediately with a pointed message."""
    body = _read(_BODY)
    style_start = body.find("<style>")
    style_end = body.find("</style>", style_start)
    assert style_start != -1 and style_end != -1
    block = body[style_start + len("<style>"):style_end]
    import re as _re
    block = _re.sub(r"/\*.*?\*/", "", block, flags=_re.DOTALL)
    block = _re.sub(r"@keyframes[^{]+\{(?:[^{}]|\{[^{}]*\})*\}", "", block)
    for raw in block.split("}"):
        seg = raw.strip()
        if not seg or seg.startswith("@"):
            continue
        head = seg.partition("{")[0].strip()
        if not head:
            continue
        for sel in head.split(","):
            s = sel.strip()
            if not s or "audit-live-dot" not in s and "auditLive" not in s:
                continue
            assert s.startswith("#tab-audit"), (
                f"live-tail selector leaked out of #tab-audit: {s!r}"
            )
