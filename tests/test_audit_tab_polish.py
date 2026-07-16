"""Tests for the Audit-tab polish (v4.6.0).

The Audit tab was upgraded from a raw-JSON tail with three-column
table to a filtered/paginated view with search, exit-code filter,
row expand and auto-refresh. Everything is client-side (bridge
/v1/audit endpoint unchanged), so these tests assert the shape of
the HTML+JS bundle rather than server behaviour.

Guards against a repeat of the v4.0.x CSS regression: the
dashboard.css baseline is byte-identical to v4.0.0; all new
styling must live inside the tab body via <style scoped>-ish
rules under ``#tab-audit``. If a future edit puts an ``.audit-*``
selector into shared CSS these tests fail immediately.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-13-audit.html"
_JS = _REPO / "dashboard" / "assets" / "16-audit.js"
_CSS = _REPO / "dashboard" / "assets" / "dashboard.css"


def _body() -> str:
    return _BODY.read_text(encoding="utf-8")


def _js() -> str:
    return _JS.read_text(encoding="utf-8")


def _css() -> str:
    return _CSS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# HTML body shape
# ---------------------------------------------------------------------------
def test_audit_body_still_has_tab_root_and_load_hook():
    """tabs-registry calls loadAudit() on tab-show; the tab root id
    must stay ``tab-audit`` so the auto-refresh helper on Overview
    can also invalidate it."""
    body = _body()
    assert 'id="tab-audit"' in body
    assert "loadAudit" in _js()  # invoked from 00-tabs-registry.js


def test_audit_body_exposes_all_control_ids_the_js_reads():
    """Any element id the JS reads via getElementById must be
    present in the body -- catches typos like ``auditFilter`` vs
    ``auditType`` before they hit runtime."""
    body = _body()
    js = _js()
    # Ids the JS is known to touch:
    ids = [
        "auditSearch", "auditFilter", "auditExit", "auditLines",
        "auditPageSize", "auditAuto", "auditRefreshDot",
        "auditTable", "auditPager", "auditMeta",
        "auditStatsPanel",
    ]
    for i in ids:
        assert f'id="{i}"' in body, f"missing id in body: {i}"
        assert i in js, f"js never touches id: {i}"


def test_audit_body_has_six_column_table_matching_js():
    """New polish uses six columns (Time, Type, Actor, Req ID,
    Detail, Exit). The JS writes ``colspan='6'`` in the empty /
    loading / error rows; if the table shrinks silently those
    would visually shift."""
    body = _body()
    js = _js()
    for header in ("Time", "Type", "Actor", "Req ID", "Detail", "Exit"):
        assert f">{header}<" in body, f"header missing: {header!r}"
    # loading/error/empty rows must span the full width.
    assert 'colspan="6"' in js or "colspan='6'" in js


# ---------------------------------------------------------------------------
# CSS containment -- the whole point of v4.0.x lesson
# ---------------------------------------------------------------------------
def test_dashboard_css_is_not_touched_by_audit_polish():
    """No ``.audit-*`` / ``.ev-badge`` / ``#tab-audit`` selectors
    may leak into the shared stylesheet. The v4.0.x regression
    (Overview drift on 100%/125% zoom) came from exactly that
    kind of shared-CSS surgery."""
    css = _css()
    for token in ("audit-toolbar", "audit-table", "audit-row",
                  "audit-pager", "ev-badge", "ev-exit-",
                  "audit-refresh-dot"):
        assert token not in css, f"selector leaked into dashboard.css: {token}"


def test_audit_body_scopes_all_new_styles_to_tab_audit():
    """Every non-keyframe rule in the tab's own <style> block must
    start with ``#tab-audit`` so nothing bleeds out into other
    tabs. Keyframes and their body are exempt (they can't cascade
    on their own)."""
    body = _body()
    style_start = body.find("<style>")
    style_end = body.find("</style>", style_start)
    assert style_start != -1 and style_end != -1, "no <style> block in body"
    block = body[style_start + len("<style>"):style_end]
    # Strip keyframes bodies -- they are exempt.
    import re as _re
    block = _re.sub(r"@keyframes[^{]+\{(?:[^{}]|\{[^{}]*\})*\}", "", block)
    # Strip C-style comments (may span multiple lines).
    block = _re.sub(r"/\*.*?\*/", "", block, flags=_re.DOTALL)
    for raw in block.split("}"):
        seg = raw.strip()
        if not seg:
            continue
        # Skip @-rules (@media, @supports, @keyframes leftover).
        if seg.startswith("@"):
            continue
        # The selector is everything before the first '{'.
        head, _, _rest = seg.partition("{")
        head = head.strip()
        if not head:
            continue
        # Each comma-separated selector must be scoped.
        for sel in head.split(","):
            s = sel.strip()
            if not s:
                continue
            assert s.startswith("#tab-audit"), (
                f"style rule leaks out of #tab-audit: {s!r}"
            )


# ---------------------------------------------------------------------------
# JS behaviour contract -- static checks (no headless browser)
# ---------------------------------------------------------------------------
def test_audit_js_exposes_loadAudit_and_auditStats_globals():
    """tabs-registry + Stats button both call these at global scope."""
    js = _js()
    assert "async function loadAudit(" in js
    assert "async function auditStats(" in js


def test_audit_js_uses_esc_for_all_dynamic_values_written_to_innerhtml():
    """Guard against XSS: every place we drop a user/audit-supplied
    string into innerHTML must go through esc(). We scan every
    physical line where 'innerHTML' or 'html +=' appears and forbid
    a raw ``+ e.<field> +`` on that line -- values in innerHTML
    concatenations must be wrapped in esc(...) at that call site.

    Deliberately conservative: helper functions (like __auditDetail)
    that build strings for later escape are exempt because their
    output goes through esc() at the innerHTML site."""
    import re
    hits = []
    for line in _js().splitlines():
        if "innerHTML" in line or "html +=" in line:
            for m in re.finditer(r"\+\s*e\.[a-zA-Z_]+\s*\+", line):
                hits.append((m.group(0), line.strip()))
    assert not hits, (
        f"unescaped audit-event fields interpolated into innerHTML: {hits!r}. "
        "Wrap with esc(...)"
    )


def test_audit_js_supports_search_type_exit_pagesize_and_autorefresh():
    """Contract: all five filter axes advertised in the toolbar are
    actually wired. Also guards against wiring drift (e.g. an
    audit polish that removes the auto-refresh interval)."""
    js = _js()
    assert 'getElementById("auditSearch")' in js
    assert 'getElementById("auditFilter")' in js
    assert 'getElementById("auditExit")' in js
    assert 'getElementById("auditPageSize")' in js
    assert "setInterval(loadAudit" in js  # auto-refresh cadence
    assert "clearInterval" in js          # ...cleared on toggle-off


def test_audit_js_categorises_event_types_deterministically():
    """The __auditCategory helper is where a new event vocabulary
    gets colored. Guarding the current mapping so a future rename
    doesn't accidentally recolor exec_blocked as tunnel."""
    js = _js()
    # Anchor: v4.3.0 introduced exec_stream_* events; classifier
    # must map them to the exec-stream / exec-blocked / exec-timeout
    # buckets rather than falling through to 'other'.
    assert "exec_stream_blocked" in js
    assert "exec-stream" in js
    assert "exec-blocked" in js
    assert "exec-timeout" in js


def test_audit_js_pagination_state_scoped_to_module():
    """Pagination state is module-scoped so tab-hide/tab-show does
    not reset the page. Guards against a refactor that moves state
    inside loadAudit() (which would reset on every reload)."""
    js = _js()
    assert "__auditState" in js
    assert "page:" in js  # state.page exists
    assert "autoTimer" in js  # state.autoTimer exists
