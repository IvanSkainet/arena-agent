"""Static structural checks for the Proposals tab (v4.25.0).

Guarantees the HTML contains every id/class the JS reaches for,
that all styles are scoped to #tab-proposals (v4.0.x lesson),
that the tab is registered in ARENA_TABS, and that the JS module
follows the same hygiene rules as the Overview toolbar module.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-19-proposals.html"
_JS = _REPO / "dashboard" / "assets" / "19-proposals.js"
_REG = _REPO / "dashboard" / "assets" / "00-tabs-registry.js"


@pytest.fixture(scope="module")
def body_html() -> str:
    return _BODY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js_text() -> str:
    return _JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def registry_text() -> str:
    return _REG.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Preserved ids the JS reaches for
# ---------------------------------------------------------------------------
REQUIRED_IDS = [
    "proposalsAuto", "proposalsInterval", "proposalsRefreshDot",
    "proposalsMeta", "proposalsTable", "proposalsTbody",
    "proposalsEmpty",
    "proposalsForm",
    "prTitle", "prRationale", "prDiff",
    "prFormResult", "prSubmitBtn", "prSubmitToggle",
]


@pytest.mark.parametrize("id_", REQUIRED_IDS)
def test_required_id_present(body_html: str, id_: str):
    assert f'id="{id_}"' in body_html


def test_tab_wrapper_present(body_html: str):
    assert 'id="tab-proposals"' in body_html
    assert '<h1>Proposals</h1>' in body_html


def test_state_badges_present_for_every_state(body_html: str):
    """Every proposal state the endpoint can produce must have a
    scoped badge class. Missing one would render as unstyled text."""
    for state in ("passed", "failed", "pending", "running",
                  "rejected", "applied"):
        assert f".st-badge.{state}" in body_html, (
            f"missing scoped badge style for state {state!r}"
        )


# ---------------------------------------------------------------------------
# Scoped CSS discipline
# ---------------------------------------------------------------------------
def test_every_style_selector_scoped_to_tab_proposals(body_html: str):
    style_blocks = re.findall(r"<style>(.*?)</style>", body_html,
                              flags=re.DOTALL)
    assert style_blocks

    def strip_comments(css: str) -> str:
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    def strip_at_rules(css: str) -> str:
        out = []
        i = 0
        while i < len(css):
            if css[i] == "@":
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
                i = j
                continue
            out.append(css[i])
            i += 1
        return "".join(out)

    for block in style_blocks:
        clean = strip_at_rules(strip_comments(block))
        for m in re.finditer(r"([^{}]+)\{[^{}]*\}", clean):
            selector_list = m.group(1).strip()
            if not selector_list or selector_list.startswith("@"):
                continue
            for selector in selector_list.split(","):
                selector = selector.strip()
                if not selector:
                    continue
                assert selector.startswith("#tab-proposals"), (
                    f"Unscoped selector in Proposals <style>: {selector!r}"
                )


def test_palette_variables_scoped_inside_tab(body_html: str):
    assert "#tab-proposals{" in body_html or "#tab-proposals {" in body_html
    for var in ("--pr-tint-green", "--pr-tint-red", "--pr-tint-blue"):
        assert var in body_html


# ---------------------------------------------------------------------------
# ARENA_TABS registration
# ---------------------------------------------------------------------------
def test_proposals_tab_registered(registry_text: str):
    """The tab must exist in 00-tabs-registry.js with an onShow
    callback that dispatches to loadProposals()."""
    assert 'name: "proposals"' in registry_text
    assert 'onShow: () => loadProposals()' in registry_text


def test_proposals_tab_between_audit_and_settings(registry_text: str):
    """Sidebar ordering: audit -> proposals -> settings. Keeps the
    meta / admin tabs grouped at the bottom of the sidebar."""
    audit_idx = registry_text.index('name: "audit"')
    proposals_idx = registry_text.index('name: "proposals"')
    settings_idx = registry_text.index('name: "settings"')
    assert audit_idx < proposals_idx < settings_idx


# ---------------------------------------------------------------------------
# JS module hygiene
# ---------------------------------------------------------------------------
def test_js_is_iife(js_text: str):
    lines = [l.strip() for l in js_text.splitlines()
             if l.strip() and not l.strip().startswith("//")]
    assert lines[0].startswith("(function")


def test_js_exports_loadProposals_globally(js_text: str):
    """Sidebar registry references loadProposals() by name;
    module must expose it on window so the onShow callback works."""
    assert "window.loadProposals" in js_text
    assert "window.submitProposal" in js_text
    assert "window.toggleProposalForm" in js_text


def test_js_uses_api_helper(js_text: str):
    """POST + GET both must go through window.api() so bearer auth
    is uniform (never a bare fetch that skips the token)."""
    assert 'window.api("/v1/admin/proposal/list")' in js_text
    assert 'window.api("/v1/admin/proposal/submit"' in js_text
    assert "await fetch(" not in js_text, (
        "Proposals tab must not bypass window.api() with a raw fetch"
    )


def test_js_exposes_diagnostic_namespace(js_text: str):
    assert "__proposalsTab" in js_text
    assert "enumerable: false" in js_text


def test_js_escapes_untrusted_strings(js_text: str):
    """Table rows come from the ledger which reflects agent-
    submitted titles/rationales -- must be HTML-escaped before
    landing in innerHTML."""
    assert "_escape(" in js_text
    # A few call sites confirming escape is actually applied.
    assert "_escape(p.title" in js_text
    assert "_escape(rationale)" in js_text


def test_js_no_hardcoded_setInterval_delay(js_text: str):
    """Same guard the Overview toolbar has -- interval selector is
    the single source of truth."""
    matches = re.findall(r"setInterval\([^,]+,\s*(\d+)\)", js_text)
    assert matches == [], (
        f"proposals JS hardcodes setInterval delays: {matches}. "
        "Read from #proposalsInterval instead."
    )


def test_js_short_id_is_deterministic(js_text: str):
    """_short() slices to 8 chars -- matches what the JSONL ledger
    uses for branch names (proposal/<short>). Guard against a
    future 'clever' change to a different length."""
    assert ".slice(0, 8)" in js_text
