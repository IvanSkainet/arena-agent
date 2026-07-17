"""Regression guards for v4.48.8 -- Dashboard-shell burst-request storm fix.

Live-reported after v4.48.7:

    Dashboard boot failed: Error: Failed to load /gui/assets/00-core.js
    {"ok": false, "error": "rate limit exceeded", "retry_after_s": 0.4}

Root cause: one Dashboard reload = 58 JS + 22 body HTML + manifest +
API calls (~85 requests) and every static asset was served with
Cache-Control:no-store so Chromium re-downloaded them on every reload.
The per-IP rate limiter (300 req/60 s) then killed the shell after
3-4 reloads. Two fixes:

1. arena/errors.py -- exempt /gui/assets/* and /gui/docs/* from the
   rate limiter middleware. These endpoints are read-only static
   assets with path-traversal guards and cannot mutate state.
2. arena/gui/handlers.py -- serve static assets with
   ``Cache-Control: public, max-age=3600, immutable`` instead of
   ``no-store``. The URLs already carry a ?v={{VERSION}} cache
   buster so a real upgrade still forces a fresh fetch.

These asserts are string-based so they survive future formatting
churn without needing a live aiohttp harness.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ERRORS_PY = REPO_ROOT / "arena" / "errors.py"
GUI_HANDLERS_PY = REPO_ROOT / "arena" / "gui" / "handlers.py"


def test_gui_assets_exempt_from_rate_limit():
    """v4.48.8: /gui/assets/* MUST be exempt from the rate limiter."""
    src = ERRORS_PY.read_text(encoding="utf-8")
    assert '_RL_SKIP_PREFIXES = ("/gui/assets/", "/gui/docs/")' in src, (
        "rate-limit skip-prefix tuple must include /gui/assets/ and /gui/docs/"
    )
    assert "any(request.path.startswith(p) for p in _RL_SKIP_PREFIXES)" in src, (
        "prefix-startswith check must guard the rate-limit call"
    )


def test_rate_limit_still_applied_to_mutation_endpoints():
    """Sanity: the rate limiter must still be invoked for paths that
    are NOT in the exemption list. We assert the same skip-list still
    includes the pre-existing entries so no other endpoint accidentally
    lost its protection."""
    src = ERRORS_PY.read_text(encoding="utf-8")
    for required in ('"/health"', '"/metrics"', '"/gui"', '"/favicon.ico"', '"/api-docs"'):
        assert required in src, f"exemption list must still include {required}"
    # And the guarded call itself must still exist:
    assert "ctx.check_rate_limit_v2(request) or ctx.check_rate_limit(request)" in src, (
        "the rate-limit call must remain wired in"
    )


def test_static_assets_use_immutable_cache_control():
    """v4.48.8: static assets must be cacheable so reloads don't
    re-download 80 files each time. The ?v={{VERSION}} cache-buster
    still forces a fresh fetch on every version bump."""
    src = GUI_HANDLERS_PY.read_text(encoding="utf-8")
    assert '"public, max-age=3600, immutable"' in src, (
        "handle_gui_asset must serve assets with a real Cache-Control"
    )
    assert '"Cache-Control": cache_ctrl' in src, (
        "handle_gui_asset must attach Cache-Control from the cache_ctrl var"
    )


def test_no_store_removed_from_asset_handler():
    """The no-store literal must NOT come back for handle_gui_asset.

    Note: handle_gui (the shell itself) still uses no-cache so a
    version bump is picked up immediately. We only touch
    handle_gui_asset -- the static-file handler."""
    src = GUI_HANDLERS_PY.read_text(encoding="utf-8")
    # The no-store literal on handle_gui (shell) still exists inside
    # 'no-store, no-cache, must-revalidate' -- we only want to check
    # that the plain FileResponse call no longer uses bare "no-store".
    assert (
        'FileResponse(asset_path, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})'
        not in src
    ), "handle_gui_asset must not go back to Cache-Control:no-store"
