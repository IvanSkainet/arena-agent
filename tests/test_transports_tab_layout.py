"""Static structural checks for the Transports tab (v4.37.0).

The new unified control surface replaces:
  * Settings tab: TS + CF start/stop
  * Terminal / curl: ngrok start/stop
  * Doctor tab: TS diagnostic (kept as diagnostic)
  * ZeroTier Central tab: ZT network + member admin (kept, orthogonal concern)

Guards here prove:
  * Every required id exists (four cards + toolbar controls)
  * Every scoped-CSS rule targets #tab-transports
  * Palette variables declared inside the tab
  * All four transport cards present with badge/url/installed IDs
  * Handler bindings for all four transports
  * Sidebar tab registered between audit and proposals
  * JS module hygiene (IIFE, uses window.api, no raw fetch,
    diagnostic namespace non-enumerable)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-20-transports.html"
_JS = _REPO / "dashboard" / "assets" / "20-transports.js"
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
# Toolbar + top-level ids
# ---------------------------------------------------------------------------
TOOLBAR_IDS = [
    "transportsAuto", "transportsInterval",
    "transportsRefreshDot", "transportsMeta",
]


@pytest.mark.parametrize("id_", TOOLBAR_IDS)
def test_toolbar_id_present(body_html: str, id_: str):
    assert f'id="{id_}"' in body_html


def test_tab_wrapper_and_h1(body_html: str):
    assert 'id="tab-transports"' in body_html
    assert '<h1>Transports' in body_html


# ---------------------------------------------------------------------------
# Every transport gets its own card with the same id shape
# ---------------------------------------------------------------------------
TRANSPORTS = ["tailscale", "zerotier", "cloudflared", "ngrok"]


@pytest.mark.parametrize("name", TRANSPORTS)
def test_card_ids_present(body_html: str, name: str):
    """Every transport must have: card container, badge, url span,
    installed span, hint container. Missing any of these silently
    breaks the loader's DOM-write."""
    for suffix in ("card", "badge", "url", "installed", "hint"):
        assert f'id="tr-{suffix}-{name}"' in body_html, (
            f"{name} card missing tr-{suffix}-{name} id"
        )


def test_ngrok_and_cloudflared_have_log_containers(body_html: str):
    """CF + NG stream stdout, so their cards carry a log-tail
    element. TS + ZT don't (no equivalent stream), so they should
    NOT have one -- keeps DOM lean."""
    assert 'id="tr-log-cloudflared"' in body_html
    assert 'id="tr-log-ngrok"' in body_html
    assert 'id="tr-log-tailscale"' not in body_html
    assert 'id="tr-log-zerotier"' not in body_html


@pytest.mark.parametrize("name", ["tailscale", "cloudflared", "ngrok"])
def test_start_stop_buttons_present(body_html: str, name: str):
    """TS/CF/NG all have real start/stop verbs -- their cards must
    expose Start + Stop buttons. ZT is deliberately different (no
    verb, only a "Manage networks" link)."""
    assert f"transportStart('{name}')" in body_html
    assert f"transportStop('{name}')" in body_html


def test_zerotier_card_has_no_start_stop(body_html: str):
    """ZT membership is managed through the ZeroTier Central tab,
    not via a start/stop verb here. Adding those buttons would
    mislead operators."""
    # zerotier still gets a Copy URL button, but NOT start/stop
    assert "transportStart('zerotier')" not in body_html
    assert "transportStop('zerotier')" not in body_html


@pytest.mark.parametrize("name", TRANSPORTS)
def test_copy_url_button_present(body_html: str, name: str):
    assert f"transportCopyUrl('{name}')" in body_html


def test_start_all_and_stop_all_buttons_present(body_html: str):
    assert "transportsStartAll()" in body_html
    assert "transportsStopAll()" in body_html


# ---------------------------------------------------------------------------
# Scoped CSS discipline (v4.0.x lesson)
# ---------------------------------------------------------------------------
def test_every_selector_scoped_to_tab_transports(body_html: str):
    style_blocks = re.findall(r"<style>(.*?)</style>", body_html, flags=re.DOTALL)
    assert style_blocks

    def strip_comments(css):
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    def strip_at_rules(css):
        out, i = [], 0
        while i < len(css):
            if css[i] == "@":
                open_b = css.find("{", i)
                if open_b < 0:
                    break
                depth, j = 1, open_b + 1
                while j < len(css) and depth > 0:
                    if css[j] == "{": depth += 1
                    elif css[j] == "}": depth -= 1
                    j += 1
                i = j
                continue
            out.append(css[i])
            i += 1
        return "".join(out)

    for block in style_blocks:
        clean = strip_at_rules(strip_comments(block))
        for m in re.finditer(r"([^{}]+)\{[^{}]*\}", clean):
            for sel in m.group(1).split(","):
                sel = sel.strip()
                if not sel or sel.startswith("@"):
                    continue
                assert sel.startswith("#tab-transports"), (
                    f"Unscoped selector: {sel!r}"
                )


def test_palette_vars_scoped(body_html: str):
    assert "#tab-transports{" in body_html or "#tab-transports {" in body_html
    for var in ("--tr-tint-green", "--tr-tint-red",
                "--tr-tint-orange", "--tr-tint-blue"):
        assert var in body_html


# ---------------------------------------------------------------------------
# Sidebar registration
# ---------------------------------------------------------------------------
def test_transports_tab_registered_between_audit_and_proposals(registry_text: str):
    assert 'name: "transports"' in registry_text
    assert 'onShow: () => loadTransports()' in registry_text
    audit_idx = registry_text.index('name: "audit"')
    tr_idx = registry_text.index('name: "transports"')
    prop_idx = registry_text.index('name: "proposals"')
    assert audit_idx < tr_idx < prop_idx


# ---------------------------------------------------------------------------
# JS module hygiene
# ---------------------------------------------------------------------------
def test_js_is_iife(js_text: str):
    lines = [l.strip() for l in js_text.splitlines()
             if l.strip() and not l.strip().startswith("//")]
    assert lines[0].startswith("(function")


def test_js_exports_load_and_transport_verbs_globally(js_text: str):
    for name in ("loadTransports", "transportStart", "transportStop",
                 "transportCopyUrl", "transportsStartAll",
                 "transportsStopAll"):
        assert f"window.{name}" in js_text, f"missing window.{name}"


def test_js_uses_api_helper_no_raw_fetch(js_text: str):
    assert "window.api(" in js_text
    assert "await fetch(" not in js_text, (
        "Transports tab must not bypass window.api() with raw fetch"
    )


def test_js_exposes_diagnostic_namespace(js_text: str):
    assert "__transportsTab" in js_text
    assert "enumerable: false" in js_text


def test_js_escapes_untrusted_strings_in_hints(js_text: str):
    """Cards render hint/error text into innerHTML via textContent
    or _escape, never as raw HTML from an untrusted source."""
    assert "_escape(" in js_text


def test_js_no_hardcoded_setInterval_delay(js_text: str):
    """Same guard the Overview + Proposals toolbars have."""
    matches = re.findall(r"setInterval\([^,]+,\s*(\d+)\)", js_text)
    assert matches == [], f"hardcoded delays: {matches}"


def test_js_start_stop_route_map_has_no_zerotier(js_text: str):
    """ZeroTier deliberately absent from _ROUTE so transportStart
    can early-return with a helpful message instead of silently
    404'ing on /v1/zerotier/tunnel/start (which doesn't exist)."""
    # Extract the _ROUTE map body.
    m = re.search(r"_ROUTE\s*=\s*\{([^}]+)\}", js_text)
    assert m, "_ROUTE map not found"
    body = m.group(1)
    assert "tailscale:" in body
    assert "cloudflared:" in body
    assert "ngrok:" in body
    # ZT explicitly NOT in the map.
    assert "zerotier:" not in body


def test_js_reads_agent_config_and_per_transport_status(js_text: str):
    """The loader hits all five status endpoints in parallel so
    one slow snapshot doesn't stall the others."""
    for endpoint in ("/v1/agent/config",
                     "/v1/tailscale/funnel/status",
                     "/v1/cloudflared/tunnel/status",
                     "/v1/ngrok/tunnel/status",
                     "/v1/zerotier/status"):
        assert endpoint in js_text


# ---------------------------------------------------------------------------
# Settings deprecation notice (v4.37.0 -> full migration in v4.47.2)
# ---------------------------------------------------------------------------
def test_settings_shows_deprecation_notice():
    """The Settings tab must still carry a visible pointer to the
    Transports tab so operators who reach for the old location find
    the new one. As of v4.47.2 the legacy per-transport DOM ids
    (tsFunnelStart / tsFunnelStop / cfFunnelStart / cfFunnelStop /
    tsToggleStatus / cfToggleStatus / cfUrl) are gone -- the block
    collapsed to a one-line info banner with a "Go to Transports
    tab" deep-link button, and the JS handlers that used those
    ids were removed rather than shimmed."""
    settings = (_REPO / "dashboard" / "assets"
                / "body-15-settings.html").read_text(encoding="utf-8")
    # Explicit pointer text present and easy to grep for.
    assert "Transports" in settings
    # The deep-link button must be present -- it is the whole
    # migration path now.
    assert "Go to Transports tab" in settings
    # The retired ids must NOT come back by accident (would resurrect
    # a duplicate control surface). Same list as tests/test_four_tabs_scoped_palette.py
    # dropped in v4.47.2.
    for retired_id in ("tsFunnelStart", "tsFunnelStop", "tsToggleStatus",
                       "cfFunnelStart", "cfFunnelStop", "cfToggleStatus",
                       "cfUrl"):
        assert f'id="{retired_id}"' not in settings, (
            f"Retired Settings-side tunnel id {retired_id!r} came back; "
            "it belongs on body-20-transports.html as a tr-* id now."
        )
