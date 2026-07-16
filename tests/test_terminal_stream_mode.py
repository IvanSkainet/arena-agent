"""Tests for the Terminal-tab stream-mode toggle (v4.13.0).

The Terminal tab has always POSTed to /v1/exec (buffered response,
stdout/stderr arrive after the command finishes). v4.13.0 adds a
"stream mode" checkbox that switches runCommand() to
POST /v1/exec/stream (v4.3.0 chunked NDJSON endpoint) and pipes
stdout/stderr chunks into the same output <pre> as they arrive.

Same containment discipline as every dashboard change since v4.6.0:
* dashboard.css untouched
* All new styling scoped to ``#tab-terminal``
* No hex literals inline (guard via scoped palette var)
* Feature-detected -- older browsers get the checkbox disabled
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-02-terminal.html"
_JS = _REPO / "dashboard" / "assets" / "05-terminal-v1-6-2-persistent-shell-like-se.js"
_CSS = _REPO / "dashboard" / "assets" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Markup
# ---------------------------------------------------------------------------
def test_body_has_stream_checkbox_and_dot_style():
    body = _read(_BODY)
    assert 'id="termStream"' in body, "stream-mode checkbox missing"
    assert ".term-stream-dot" in body, "streaming pulse dot style missing"
    assert ".term-kill-btn" in body, "kill button style missing"


def test_body_scopes_all_new_styles_to_tab_terminal():
    """Every non-keyframe rule in the tab's <style> must be scoped
    to ``#tab-terminal`` so nothing leaks. Same shape as the audit-
    polish guard in v4.6.0."""
    body = _read(_BODY)
    start = body.find("<style>")
    end = body.find("</style>", start)
    assert start != -1 and end != -1, "no <style> block in body"
    block = body[start + len("<style>"):end]
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
            if not s:
                continue
            assert s.startswith("#tab-terminal"), (
                f"terminal style leaks out of #tab-terminal: {s!r}"
            )


# ---------------------------------------------------------------------------
# JS behaviour contract
# ---------------------------------------------------------------------------
def test_js_exposes_stream_helpers():
    js = _read(_JS)
    for name in ("__termStreamSupported", "_runStreamedCommand"):
        assert name in js, f"missing helper: {name}"


def test_js_streamed_command_uses_correct_endpoint():
    """POST /v1/exec/stream is the v4.3.0 NDJSON endpoint. Not
    /v1/exec (buffered) -- that's the fallback path."""
    js = _read(_JS)
    assert '"/v1/exec/stream"' in js
    assert 'method: "POST"' in js


def test_js_handles_all_ndjson_event_types_from_v430():
    """v4.3.0 emits meta, start, stdout, stderr, exit. All five
    must be handled explicitly (start reveals pid, stdout/stderr
    stream to the pre, exit tags the badge)."""
    js = _read(_JS)
    for t in ('"meta"', '"start"', '"stdout"', '"stderr"', '"exit"'):
        assert t in js, f"stream event type not handled: {t}"


def test_js_captures_request_id_from_meta_event():
    """The Kill button needs the request_id from the meta event to
    POST /v1/kill. Without capturing it, killing a streamed job
    falls through to client-side AbortController only (which
    leaves the server-side process running)."""
    js = _read(_JS)
    assert "requestId" in js
    assert "ev.request_id" in js
    assert '"/v1/kill"' in js


def test_js_uses_abort_controller_for_clean_stop():
    """Kill button must abort the fetch client-side so the browser
    doesn't keep buffering after the server-side process is dead."""
    js = _read(_JS)
    assert "AbortController" in js
    assert "controller.abort" in js or ".abort()" in js


def test_js_appends_output_incrementally_not_at_end():
    """The whole point of stream mode is that stdout appears while
    the command runs. Regression guard against a future edit that
    accidentally collects everything into a string and writes it
    once at the end."""
    js = _read(_JS)
    # stdoutText and stderrText accumulators exist.
    assert "stdoutText +=" in js or "stdoutText+=" in js
    assert "stderrText +=" in js or "stderrText+=" in js
    # And they get written to slot.out.textContent inside the
    # per-chunk branch, not just at the end.
    # Grep the _runStreamedCommand body for exactly this pattern.
    start = js.find("async function _runStreamedCommand(")
    assert start != -1
    end = js.find("\nasync function ", start + 1)
    if end == -1:
        end = js.find("\nfunction ", start + 1)
    body = js[start:end] if end != -1 else js[start:]
    # Count how many places set slot.out.textContent inside the
    # stream body. Must be > 1 (per-chunk render) plus the final
    # summary render.
    n = body.count("slot.out.textContent =")
    assert n >= 2, (
        f"stream mode writes slot.out.textContent only {n} times; "
        "expected at least one per-chunk write + one final render"
    )


def test_js_feature_detects_readablestream():
    """Older browsers without ReadableStream must NOT go through the
    stream branch (they'd throw). The checkbox is disabled with a
    tooltip, and runCommand falls back to buffered /v1/exec."""
    js = _read(_JS)
    assert "__termStreamSupported" in js
    assert "ReadableStream" in js
    # runCommand consults the probe before switching branches.
    assert "wantStream" in js or "__termStreamSupported()" in js


def test_js_falls_back_to_buffered_when_checkbox_off_or_unsupported():
    """The buffered POST /v1/exec branch must survive. Regression
    guard: someone rewriting the toggle logic might accidentally
    remove the buffered path (breaking every host on an old
    browser)."""
    js = _read(_JS)
    assert 'api("/v1/exec"' in js, (
        "buffered /v1/exec branch removed! this breaks old browsers"
    )
    # Both branches must save history the same way.
    assert "cmdHistory.unshift(c)" in js


def test_js_updates_execs_metric_in_both_branches():
    """Overview's Exec count metric should tick regardless of which
    branch handled the request. Regression guard against a future
    edit that only increments on one path."""
    js = _read(_JS)
    # Both branches touch overviewMetrics.execs. Rough grep suffices
    # (both are in this file, no others touch it).
    n = js.count("overviewMetrics.execs")
    assert n >= 2, (
        f"overviewMetrics.execs incremented in only {n} branch(es); "
        "both stream and buffered runCommand paths must tick it"
    )


def test_js_disables_checkbox_when_readable_stream_missing():
    """Init block on script load must disable the checkbox on
    unsupported browsers so the user doesn't chase a mystery no-op
    click."""
    js = _read(_JS)
    assert "box.disabled = true" in js
    assert "_initStreamToggle" in js or "initStreamToggle" in js


# ---------------------------------------------------------------------------
# Containment (v4.0.x lesson)
# ---------------------------------------------------------------------------
def test_dashboard_css_untouched_by_terminal_stream():
    css = _read(_CSS)
    for token in ("term-kill-btn", "term-stream-dot", "termStream",
                  "term-stream-pulse"):
        assert token not in css, f"leaked into dashboard.css: {token}"


def test_body_defines_kill_hover_via_scoped_palette_var_no_hex_inline():
    """The kill button's :hover uses a scoped palette variable
    (var(--term-kill-hover)) rather than a bare hex literal --
    otherwise test_no_hardcoded_theme_colors would fail. Guards
    that the var stays defined inside #tab-terminal."""
    body = _read(_BODY)
    assert "--term-kill-hover" in body
    assert "var(--term-kill-hover)" in body
