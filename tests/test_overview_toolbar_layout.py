"""Static structural checks for the redesigned Overview tab.

The Overview redesign adds a toolbar (mirroring the Audit tab's
visual language) and consolidates per-section styles into a
single scoped ``<style>`` block. Losing any of the ids listed
below would silently break loaders in ``04-overview.js``,
``04b-zt-peers.js``, ``04c-net-breaker.js`` and
``21b-hwinfo-overview-extensions.js``.

These tests are pure-string checks (no browser needed) so they
run in any CI environment. They complement the JS-side sanity
check in ``tests/test_overview_toolbar_js.py`` which uses Node.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-01-overview.html"
_JS = _REPO / "dashboard" / "assets" / "04d-overview-toolbar.js"


@pytest.fixture(scope="module")
def body_html() -> str:
    return _BODY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def toolbar_js() -> str:
    return _JS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# preserved ids -- if any of these disappear, JS loaders silently break
# ---------------------------------------------------------------------------
PRESERVED_IDS = [
    # Stats grid (04-overview.js)
    "statVersion", "statHost", "statUptime", "statCPU", "statRAM", "statDisk",
    "statMemory", "statMissions", "statActiveTasks", "statProfile",
    "versionTag",
    # Resource usage
    "cpuBar", "cpuText", "ramBar", "ramText", "diskBar", "diskText",
    "loadAvgRow", "loadAvgText",
    # Network status
    "networkCard", "netActiveProvider", "netActiveUrl", "netProvidersList",
    "netProvidersRow", "netBreakerRow", "netBreakerList",
    "tsFunnelStatus", "tsFunnelUrl",  # legacy IDs kept for compatibility
    # ZeroTier peers (04b-zt-peers.js)
    "ztPeersHeader", "ztPeersCard", "ztDonut", "ztLegend", "ztStats",
    "ztHint", "ztMeta",
    # Agent control
    "overviewControlBadge", "controlOverviewCard", "overviewControlState",
    "overviewActiveWindow", "overviewPauseBtn", "overviewResumeBtn",
    # Bridge metrics
    "metricReqs", "metricExecs", "metricErrors",
    # Platform info
    "platformCard", "platPython", "platOS", "platArch",
    # Hardware diagnostics
    "hwinfoCard", "hwSource", "hwDetails", "invToggleBtn",
    "fullInventoryCard", "invStatus", "invViewModeBtn",
    "invSectionStrip", "invOutput",
]


@pytest.mark.parametrize("id_", PRESERVED_IDS)
def test_preserved_id_still_present(body_html: str, id_: str):
    """Every id the existing JS reaches for must still exist."""
    needle = f'id="{id_}"'
    assert needle in body_html, (
        f"Overview redesign removed #{id_} -- would silently break "
        f"an existing loader. Restore before shipping."
    )


# ---------------------------------------------------------------------------
# new toolbar ids added by the redesign
# ---------------------------------------------------------------------------
NEW_TOOLBAR_IDS = [
    "overviewAuto", "overviewInterval", "overviewRefreshDot", "overviewMeta",
]


@pytest.mark.parametrize("id_", NEW_TOOLBAR_IDS)
def test_new_toolbar_id_present(body_html: str, id_: str):
    assert f'id="{id_}"' in body_html


# ---------------------------------------------------------------------------
# scoped CSS discipline (v4.0.x lesson enforcement)
# ---------------------------------------------------------------------------
def test_all_style_rules_scoped_to_tab_overview(body_html: str):
    """Every non-comment CSS rule in the tab's <style> block must
    start with ``#tab-overview`` -- no unscoped selectors that
    could bleed into other tabs (v4.0.x CSS lesson)."""
    import re
    style_blocks = re.findall(r"<style>(.*?)</style>", body_html,
                              flags=re.DOTALL)
    assert style_blocks, "Overview must have at least one <style> block"

    # Strip /* ... */ comments so we only look at real rules.
    def strip_comments(css: str) -> str:
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    def strip_at_rules(css: str) -> str:
        """Remove @keyframes / @media / etc blocks recursively so the
        top-level selector extraction doesn't trip over nested
        percentage keyframe selectors (0% / 50% / 100%)."""
        out = []
        i = 0
        while i < len(css):
            if css[i] == "@":
                # Find matching outer '{' and skip until its matching '}'.
                open_pos = css.find("{", i)
                if open_pos < 0:
                    break
                depth = 1
                j = open_pos + 1
                while j < len(css) and depth > 0:
                    if css[j] == "{":
                        depth += 1
                    elif css[j] == "}":
                        depth -= 1
                    j += 1
                i = j  # skip past the closing '}'
                continue
            out.append(css[i])
            i += 1
        return "".join(out)

    for block in style_blocks:
        clean = strip_comments(block)
        clean_no_at = strip_at_rules(clean)
        for match in re.finditer(r"([^{}]+)\{[^{}]*\}", clean_no_at):
            selector_list = match.group(1).strip()
            if not selector_list or selector_list.startswith("@"):
                continue
            for selector in selector_list.split(","):
                selector = selector.strip()
                if not selector:
                    continue
                assert selector.startswith("#tab-overview"), (
                    f"Unscoped selector in Overview <style>: {selector!r} -- "
                    f"every rule must start with '#tab-overview' to keep "
                    f"the tab's styling contained."
                )


def test_scoped_palette_variables_declared_inside_tab(body_html: str):
    """Palette variables should be declared on ``#tab-overview{...}``
    so they cannot leak to :root and clash with other tabs."""
    assert "#tab-overview{" in body_html or "#tab-overview {" in body_html
    for var in ("--ov-tint-green", "--ov-tint-blue", "--ov-tint-red",
                "--ov-label-w"):
        assert var in body_html, f"missing scoped palette var {var}"


# ---------------------------------------------------------------------------
# toolbar wiring
# ---------------------------------------------------------------------------
def test_toolbar_has_reload_button(body_html: str):
    """Reload button must call the existing global refreshOverview()."""
    assert 'onclick="refreshOverview()"' in body_html


def test_toolbar_interval_selector_offers_reasonable_values(body_html: str):
    """5/15/30/60 second choices -- symmetric with common polling."""
    for value in ('value="5"', 'value="15"', 'value="30"', 'value="60"'):
        assert value in body_html, f"missing interval option {value}"


def test_toolbar_meta_line_has_element(body_html: str):
    assert 'id="overviewMeta"' in body_html


# ---------------------------------------------------------------------------
# toolbar JS module hygiene
# ---------------------------------------------------------------------------
def test_toolbar_js_is_iife(toolbar_js: str):
    """Module must wrap in an IIFE so it doesn't leak locals."""
    assert toolbar_js.lstrip().startswith("// =====")
    # first non-comment line should be `(function...`
    lines = [l.strip() for l in toolbar_js.splitlines()
             if l.strip() and not l.strip().startswith("//")]
    assert lines, "toolbar JS is empty"
    assert lines[0].startswith("(function")


def test_toolbar_js_wraps_existing_refreshOverview(toolbar_js: str):
    """The wrapper must read window.refreshOverview and replace it,
    not redefine it from scratch (that would clobber 04-overview.js)."""
    assert "window.refreshOverview" in toolbar_js
    assert "_originalRefresh" in toolbar_js


def test_toolbar_js_exposes_diagnostic_namespace(toolbar_js: str):
    """__overviewToolbar is the hook the smoke test and future
    dashboard debugging can inspect. Must exist and be non-enumerable."""
    assert "__overviewToolbar" in toolbar_js
    assert "enumerable: false" in toolbar_js


def test_toolbar_js_no_hardcoded_intervals(toolbar_js: str):
    """The interval must be read from the DOM, not hardcoded, so
    the interval <select> is the single source of truth."""
    import re
    # Look for numeric setInterval(..., NNN * 1000) patterns.
    matches = re.findall(r"setInterval\([^,]+,\s*(\d+)\)", toolbar_js)
    assert matches == [], (
        f"toolbar JS has hardcoded setInterval delays: {matches}. "
        f"Read from #overviewInterval instead."
    )


# ---------------------------------------------------------------------------
# safety: JS is loaded via the auto-manifest (04d-* prefix keeps
# it in the overview group of load order)
# ---------------------------------------------------------------------------
def test_toolbar_js_prefix_sorts_after_04c(toolbar_js: str):
    """The 04d- prefix places the module after 04-overview.js,
    04b-zt-peers.js, 04c-net-breaker.js -- which is required
    because it wraps the global refreshOverview those files define
    or depend on."""
    assert _JS.name == "04d-overview-toolbar.js"
