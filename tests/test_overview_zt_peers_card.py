"""Tests for the Overview ZeroTier peers card (v4.7.0).

Small Dashboard card added on the Overview tab that visualises the
output of /v1/zerotier/peers (v4.4.0 API refined in v4.5.0) as an
inline SVG donut + legend + summary + optional hint. The card is
hidden by default and only shown when the bridge reports a
working ZeroTier backend.

Same containment rules as the Audit-tab polish (v4.6.0):
* dashboard.css untouched
* all new styling scoped to ``#tab-overview #ztPeersCard``
* no hex color literals inline (uses ``var(--foo)``)
* fail-soft: hides the card on error instead of showing broken UI
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-01-overview.html"
_JS   = _REPO / "dashboard" / "assets" / "04b-zt-peers.js"
_OVERVIEW_JS = _REPO / "dashboard" / "assets" / "04-overview.js"
_CSS  = _REPO / "dashboard" / "assets" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Body shape
# ---------------------------------------------------------------------------
def test_body_has_zt_peers_card_and_all_ids_the_js_reads():
    body = _read(_BODY)
    js = _read(_JS)
    for i in ("ztPeersCard", "ztPeersHeader", "ztDonut", "ztLegend",
              "ztStats", "ztHint", "ztMeta"):
        assert f'id="{i}"' in body, f"missing id in body: {i}"
        assert i in js, f"js never touches id: {i}"


def test_body_card_is_hidden_by_default_via_class_toggle():
    """The card must NOT show up on hosts without ZeroTier -- start
    hidden, JS opens it via .on class only after a successful
    /v1/zerotier/peers response."""
    body = _read(_BODY)
    js = _read(_JS)
    # display:none on the card itself (scoped via #tab-overview #ztPeersCard)
    assert "#tab-overview #ztPeersCard{display:none}" in body
    # class 'on' flips it back to visible
    assert "#ztPeersCard.on" in body
    # Loader must toggle the class, not directly set style.display.
    assert "classList.add(\"on\")" in js
    assert "classList.remove(\"on\")" in js


def test_body_has_manual_refresh_button():
    assert 'onclick="refreshZtPeers()"' in _read(_BODY)


# ---------------------------------------------------------------------------
# JS behaviour contract
# ---------------------------------------------------------------------------
def test_js_exposes_global_refreshZtPeers():
    """Overview refreshOverview() calls it; must be a global."""
    js = _read(_JS)
    assert "async function refreshZtPeers(" in js


def test_js_calls_correct_endpoint():
    js = _read(_JS)
    assert '"/v1/zerotier/peers"' in js


def test_js_hides_card_when_endpoint_fails_or_unavailable():
    """Fail-soft: no ZeroTier / auth failure / network drop must
    hide the card, not leave stale numbers or crash the tab."""
    js = _read(_JS)
    # Try/catch around api(...) with an explicit hide branch.
    assert "__ztHideCard" in js
    # Explicit .installed === false branch (matches zerotier_peers
    # top-level shape).
    assert "installed === false" in js


def test_js_covers_all_path_kinds_from_v450_api():
    """Palette + legend must cover every path_kind the server can
    return (direct / relay / tunneled / root / none). New kinds
    added by a future release would need explicit entries here so
    they don't silently render as blank slices."""
    js = _read(_JS)
    for kind in ("direct", "relay", "tunneled", "root", "none"):
        assert '"' + kind + '"' in js, f"path_kind missing from JS: {kind}"


def test_js_uses_v450_summary_fields():
    """Summary block reads the v4.5.0-added relay_via breakdown
    (leaf_relay_planet / leaf_relay_tcp_infra) and the existing
    direct_ratio + leaf_latency_ms_avg."""
    js = _read(_JS)
    assert "leaf_relay_planet" in js
    assert "leaf_relay_tcp_infra" in js
    assert "direct_ratio" in js
    assert "leaf_latency_ms_avg" in js


def test_js_uses_esc_on_all_dynamic_strings_written_to_innerhtml():
    """Same XSS guard shape as tests/test_audit_tab_polish.py:
    scan each innerHTML line for raw ``+ data.field +`` /
    ``+ e.field +`` interpolations that would embed unescaped
    strings into the DOM."""
    import re
    js = _read(_JS)
    hits = []
    for line in js.splitlines():
        if "innerHTML" not in line:
            continue
        # ``+ ident +`` where ident is a plausible unescaped field
        # reference. ``__ZT_KIND_*`` maps and computed pcts are ok
        # because they are numeric / whitelisted constants -- but
        # the regex catches ``data.foo`` / ``e.foo`` / ``d.foo``.
        for m in re.finditer(r"\+\s*(?:data|d|e)\.[a-zA-Z_]+\s*\+", line):
            hits.append((m.group(0), line.strip()))
    assert not hits, (
        f"unescaped fields in innerHTML: {hits!r}. Wrap with esc()."
    )


# ---------------------------------------------------------------------------
# Overview wiring
# ---------------------------------------------------------------------------
def test_overview_refresh_calls_zt_peers_loader():
    """The Overview refresh cycle must trigger the ZeroTier peers
    refresh -- otherwise the card only updates on manual click."""
    overview = _read(_OVERVIEW_JS)
    assert "refreshZtPeers" in overview
    # Must be inside a fail-soft wrapper so a ZT endpoint error
    # can't take down the whole Overview refresh.
    assert 'typeof refreshZtPeers === "function"' in overview
    assert ".catch(" in overview  # any .catch handler present


# ---------------------------------------------------------------------------
# CSS containment -- v4.0.x lesson still active
# ---------------------------------------------------------------------------
def test_dashboard_css_not_touched_by_zt_peers_card():
    """No zt-* / ztPeers* / ztDonut selectors allowed in the shared
    stylesheet. The v4.0.x CSS regression came from exactly that."""
    css = _read(_CSS)
    for token in ("zt-donut", "zt-legend", "zt-hint", "zt-meta",
                  "zt-stats", "zt-row", "ztPeersCard", "ztDonut"):
        assert token not in css, f"selector leaked into dashboard.css: {token}"


def test_body_scopes_zt_peers_styles_to_tab_overview():
    """The <style> block added for the ZT peers card must scope
    every rule to ``#tab-overview #ztPeersCard...`` so nothing
    bleeds out into other tabs or other Overview cards. Comments
    and @keyframes are exempted."""
    body = _read(_BODY)
    # Find the <style> block that mentions zt-donut -- there may be
    # multiple <style> blocks in the body over time, we need the one
    # for the ZT card.
    start = body.find("<style>")
    while start != -1:
        end = body.find("</style>", start)
        assert end != -1
        block = body[start + len("<style>"):end]
        if "zt-donut" in block or "ztPeersCard" in block:
            import re
            # Strip comments and keyframe bodies.
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
                        f"ZT peers style leaks out of #tab-overview: {s!r}"
                    )
            return
        start = body.find("<style>", end)
    raise AssertionError("no <style> block containing ZT peers rules found")


# ---------------------------------------------------------------------------
# SVG donut sanity
# ---------------------------------------------------------------------------
def test_js_builds_donut_via_svg_arithmetic():
    """The donut uses the ``r=15.9155`` trick (circumference == 100)
    so stroke-dasharray values are literal percentages. Guarding
    the constant so an accidental radius bump doesn't silently
    distort every slice."""
    js = _read(_JS)
    assert "15.9155" in js
    # Background ring + at least one <circle> template
    assert "<circle" in js
    # Text at the donut center -- total + label
    assert "<text" in js
    assert ">peers<" in js  # inner label survived
