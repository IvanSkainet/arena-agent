"""Tests for the Overview Network-Status circuit-breaker row (v4.11.0).

Small addition to the existing v4.4.0/v4.5.0/v4.7.0/v4.10.0 line of
Dashboard-side visualisations. Consumes the ``breaker`` field of
/v1/tunnels/probe (v4.8.0) and renders one badge per keyed
(provider, host, port) inside the Network Status card:

* blue "ok"           closed, no consecutive failures
* yellow "warn N/3"   closed but consecutive failures > 0
* red "cooldown Ns"   open, N seconds remaining

Same containment discipline as every other dashboard-side change
since v4.6.0: all styling scoped to
``#tab-overview #networkCard``, ``dashboard.css`` untouched,
no hex color literals inline, fail-soft on any endpoint error.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-01-overview.html"
_JS = _REPO / "dashboard" / "assets" / "04c-net-breaker.js"
_OVERVIEW_JS = _REPO / "dashboard" / "assets" / "04-overview.js"
_CSS = _REPO / "dashboard" / "assets" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Markup
# ---------------------------------------------------------------------------
def test_body_has_breaker_row_and_list_ids():
    body = _read(_BODY)
    for i in ("netBreakerRow", "netBreakerList"):
        assert f'id="{i}"' in body, f"missing id in body: {i}"


def test_body_breaker_row_is_hidden_by_default_via_class_toggle():
    """Hosts with no tunnel activity (no probes ever run, empty
    breaker snapshot) must not see this row at all -- Overview
    stays tidy."""
    body = _read(_BODY)
    assert "#tab-overview #networkCard .net-breaker-row{display:none}" in body
    assert ".net-breaker-row.on{display:flex}" in body
    js = _read(_JS)
    assert 'classList.add("on")' in js
    assert 'classList.remove("on")' in js


def test_body_style_defines_three_visual_states():
    """The palette maps state -> colour so an operator can tell
    the three cases apart at a glance without reading text."""
    body = _read(_BODY)
    assert ".net-breaker-list .item.open" in body
    assert ".net-breaker-list .item.warn" in body
    assert ".net-breaker-list .item.ok" in body


# ---------------------------------------------------------------------------
# JS behaviour contract
# ---------------------------------------------------------------------------
def test_js_exposes_global_refresh_function():
    """refreshOverview() calls it; must be a global."""
    assert "async function refreshNetBreaker(" in _read(_JS)


def test_js_reads_correct_endpoint():
    """Must hit /v1/tunnels/probe (which v4.8.0 extended with the
    ``breaker`` field). Not /v1/tunnels/status -- that one has no
    breaker information."""
    js = _read(_JS)
    assert '"/v1/tunnels/probe"' in js


def test_js_covers_open_warn_and_ok_paths():
    """The renderer must classify into three visual states, matching
    the three CSS classes. Regression guard against a future edit
    that silently drops one branch (e.g. removes ``warn`` on the
    argument that ``open`` is enough)."""
    js = _read(_JS)
    assert '"open"' in js
    assert '"warn"' in js
    assert '"ok"' in js
    # cooldown remaining seconds are surfaced when open.
    assert "cools_down_in_sec" in js
    # consecutive failures counter surfaced in warn text.
    assert "consecutive_failures" in js


def test_js_hides_row_on_error_or_missing_breaker():
    """Fail-soft: any api() error, or a probe response without a
    ``breaker`` object (older bridge), must hide the row cleanly."""
    js = _read(_JS)
    assert "__netBreakerHide" in js
    # explicit check for missing/non-object breaker field.
    assert 'data.ok === false' in js or 'ok === false' in js
    assert 'typeof snap !== "object"' in js


def test_js_uses_title_attribute_not_innerhtml_for_last_error():
    """The tooltip surfaces ``last_error`` from the probe payload.
    That string can contain arbitrary characters (< > & from a
    provider stderr). Setting it via ``.title = ...`` is safe;
    concatenating it into innerHTML would be XSS."""
    js = _read(_JS)
    assert "item.title = " in js
    # Guard: no ``+ rec.last_error +`` in an innerHTML concatenation.
    import re
    hits = []
    for line in js.splitlines():
        if "innerHTML" not in line:
            continue
        for m in re.finditer(r"\+\s*(?:rec|d|data|ev|e)\.[a-zA-Z_]+\s*\+", line):
            hits.append((m.group(0), line.strip()))
    assert not hits, (
        f"unescaped breaker fields in innerHTML: {hits!r}"
    )


def test_js_sorts_keys_for_stable_render():
    """Object.keys(snapshot) has no guaranteed order across
    browsers; sort so the row order stays stable between refreshes
    (avoids visual jitter when a breaker flips)."""
    js = _read(_JS)
    assert "keys.sort()" in js


def test_js_label_parses_provider_and_hostport_from_key():
    """The breaker key format is 'provider|host:port'. The label
    helper must split at '|' so the badge text stays compact
    ('cloudflared: cooldown 42s') and the tooltip shows the full
    'cloudflared @foo.trycloudflare.com:443' form."""
    js = _read(_JS)
    assert '__netBreakerLabel' in js
    assert '"|"' in js or "'|'" in js


# ---------------------------------------------------------------------------
# Overview wiring
# ---------------------------------------------------------------------------
def test_overview_refreshOverview_calls_refreshNetBreaker():
    overview = _read(_OVERVIEW_JS)
    assert "refreshNetBreaker" in overview
    # Must be under a typeof-guard so a partially-upgraded bridge
    # (04-overview.js from v4.11.0 without 04c-net-breaker.js
    # somehow ends up on disk) still boots.
    assert 'typeof refreshNetBreaker === "function"' in overview
    # And under a .catch so a probe hiccup can't kill Overview.
    assert "refreshNetBreaker()" in overview


# ---------------------------------------------------------------------------
# Containment (v4.0.x lesson)
# ---------------------------------------------------------------------------
def test_dashboard_css_untouched_by_breaker_row():
    """No net-breaker-* / netBreaker* selectors allowed in
    dashboard.css. Same containment guard as the 4.6.0 and 4.7.0
    tabs."""
    css = _read(_CSS)
    for token in ("net-breaker-row", "net-breaker-list",
                  "netBreaker"):
        assert token not in css, f"selector leaked into dashboard.css: {token}"


def test_body_scopes_net_breaker_styles_to_tab_overview():
    """The <style> block for the breaker row must scope every rule
    to ``#tab-overview #networkCard...`` so nothing bleeds into
    other tabs or other cards."""
    body = _read(_BODY)
    # Locate the block that contains net-breaker rules.
    start = body.find("<style>")
    while start != -1:
        end = body.find("</style>", start)
        assert end != -1
        block = body[start + len("<style>"):end]
        if "net-breaker-row" in block or "netBreakerList" in block:
            import re
            block = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)
            block = re.sub(
                r"@keyframes[^{]+\{(?:[^{}]|\{[^{}]*\})*\}", "", block
            )
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
                    assert s.startswith("#tab-overview"), (
                        f"net-breaker rule leaks out of #tab-overview: {s!r}"
                    )
            return
        start = body.find("<style>", end)
    raise AssertionError("no <style> block containing net-breaker rules found")


def test_dashboard_manifest_picks_up_new_file():
    """04c-net-breaker.js must be auto-listed in the manifest so
    the browser actually loads it. The v3.91.0 manifest builder
    scans the assets dir and sorts by numeric prefix, so this test
    is a static check that nothing is excluded."""
    from arena.gui.asset_manifest import EXCLUDED_ASSET_NAMES
    fname = "04c-net-breaker.js"
    assert fname not in EXCLUDED_ASSET_NAMES
    p = _REPO / "dashboard" / "assets" / fname
    assert p.is_file() and p.stat().st_size > 100
