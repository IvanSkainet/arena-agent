"""Regression guards for the v4.48.7 Dashboard boot hardening.

Two live-reported symptoms this pin down:

1. "Dashboard boot failed: asset manifest empty and no fallback list
   configured." shown on repeated reload -- the browser fetched
   /gui/assets/manifest.json, got a transient network hiccup, and
   the shell had NO retry and NO synchronous fallback. The retry
   logic already existed for script <script> tags but not for the
   manifest itself. We now retry 3x with 250/500 ms backoff and
   ship an embedded SYNC_FALLBACK_SCRIPTS list so the shell always
   renders at least the sidebar + tab registry.

2. Transports + Live tabs "slid to the right" because .main was a
   flex child with default min-width:auto -- a wide grid card
   pushed the container past 100vw. Fixed in dashboard.css with an
   appended .main{min-width:0;overflow-x:hidden;max-width:100%}
   block.

These asserts are intentionally string-based so they survive any
future JS/CSS reformatting without needing a live browser.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_HTML = REPO_ROOT / "dashboard" / "index.html"
DASHBOARD_CSS = REPO_ROOT / "dashboard" / "assets" / "dashboard.css"


def test_manifest_fetch_has_retry():
    """v4.48.7: /gui/assets/manifest.json must retry on transient
    failure the same way individual <script> tags do (v3.85.3)."""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "async function fetchManifest" in html, (
        "manifest fetch must be wrapped in a retryable helper"
    )
    # 3 tries with backoff (matches the script-tag loader exactly).
    assert "const attempts = 3" in html, "manifest fetch must attempt >=3 times"
    assert "setTimeout(r, 250 * i)" in html, (
        "manifest fetch must back off between retries"
    )


def test_sync_fallback_list_is_shipped():
    """v4.48.7: even when the manifest endpoint is genuinely down we
    must render the shell + tab registry so the user sees a real
    error next to a real sidebar, not a bare <pre>."""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "SYNC_FALLBACK_SCRIPTS" in html
    assert "SYNC_FALLBACK_BODIES" in html
    # The five entry scripts required for the tab registry + api
    # helpers must be in the sync fallback:
    for required in [
        "/gui/assets/00-core.js",
        "/gui/assets/00-tabs-registry.js",
        "/gui/assets/01-tab-switching.js",
        "/gui/assets/02-api-helper.js",
        "/gui/assets/03-helpers.js",
    ]:
        assert required in html, f"sync fallback missing {required}"
    assert "/gui/assets/body-00-shell.html" in html, (
        "sync fallback must at least render the shell body"
    )


def test_fallback_banner_surfaces_to_user():
    """v4.48.7: when we boot from the sync fallback we must show a
    visible warning so the operator knows most tabs are unavailable."""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "ARENA_DASHBOARD_USING_FALLBACK" in html
    assert "Dashboard booted in fallback mode" in html


def test_main_has_min_width_zero_and_overflow_x_hidden():
    """v4.48.7: the .main flex child must have min-width:0 so grid
    cards can shrink instead of pushing the sidebar off-screen.

    Regression trigger: Transports + Live tabs slid to the right on
    live testing because #tab-transports .tr-grid uses
    grid-template-columns:repeat(auto-fit,minmax(340px,1fr)) which,
    without min-width:0 on the parent, resolves to auto (== content
    width) and blows past 100vw."""
    css = DASHBOARD_CSS.read_text(encoding="utf-8")
    assert ".main{min-width:0;overflow-x:hidden;max-width:100%}" in css, (
        "dashboard.css must clamp .main horizontal overflow"
    )
    assert ".main .tab{max-width:100%;min-width:0}" in css, (
        "dashboard.css must clamp .tab horizontal overflow"
    )


def test_shell_still_has_bail_out_message():
    """The old 'asset manifest empty' bail-out message stays as the
    final last-resort branch so a code review can still grep for it,
    but it should now be genuinely unreachable in practice."""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "asset manifest empty and no fallback list configured" in html
