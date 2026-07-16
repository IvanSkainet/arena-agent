"""Layout guards for the v4.38.0 autostart checkbox row on the
Transports tab.

Each of the three verb-capable transports (tailscale,
cloudflared, ngrok) gets an autostart checkbox + env-pill.
ZeroTier explicitly does NOT (no start/stop verb).

Guards:
  * checkbox + env-pill ids present per transport
  * ZT has neither (confirms design)
  * onchange handler wired
  * JS reads /v1/autostart in the parallel loader
  * transportAutostartToggle exported globally
  * env-override renders the pill on (via class="on")
  * checkbox becomes disabled when env-override is active
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-20-transports.html"
_JS = _REPO / "dashboard" / "assets" / "20-transports.js"


@pytest.fixture(scope="module")
def body_html() -> str:
    return _BODY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js_text() -> str:
    return _JS.read_text(encoding="utf-8")


AUTOSTART_TRANSPORTS = ["tailscale", "cloudflared", "ngrok"]


@pytest.mark.parametrize("name", AUTOSTART_TRANSPORTS)
def test_autostart_checkbox_id_present(body_html: str, name: str):
    assert f'id="tr-autostart-{name}"' in body_html


@pytest.mark.parametrize("name", AUTOSTART_TRANSPORTS)
def test_autostart_env_pill_id_present(body_html: str, name: str):
    assert f'id="tr-env-{name}"' in body_html


@pytest.mark.parametrize("name", AUTOSTART_TRANSPORTS)
def test_autostart_checkbox_wired_to_toggle_handler(body_html: str, name: str):
    """onchange must fire transportAutostartToggle('<name>',
    this.checked). Missing / mistyped -> UI silently does
    nothing."""
    pattern = f"transportAutostartToggle('{name}', this.checked)"
    assert pattern in body_html


def test_zerotier_has_no_autostart_row(body_html: str):
    """ZT deliberately absent -- membership survives restarts,
    no per-bridge autostart makes sense. Adding a checkbox
    there would mislead operators."""
    assert 'id="tr-autostart-zerotier"' not in body_html
    assert 'id="tr-env-zerotier"' not in body_html
    assert "transportAutostartToggle('zerotier'" not in body_html


def test_scoped_css_for_autostart_row(body_html: str):
    """The .tr-autostart row must be scoped under #tab-transports
    like every other rule in the tab (v4.0.x lesson enforced by
    test_transports_tab_layout::test_every_selector_scoped_to_tab_transports).
    Belt-and-suspenders: additional grep here so a future edit
    that adds bare .tr-autostart selector gets caught in this
    file too."""
    assert "#tab-transports .tr-autostart" in body_html
    assert "#tab-transports .tr-autostart input[type=checkbox]" in body_html


def test_env_pill_hidden_by_default(body_html: str):
    """The pill only becomes visible via .env-pill.on class --
    absent by default so a fresh install shows nothing."""
    assert ".env-pill{" in body_html and "display:none" in body_html
    assert ".env-pill.on{" in body_html


# ---------------------------------------------------------------------------
# JS-side
# ---------------------------------------------------------------------------
def test_js_registers_autostart_transports_constant(js_text: str):
    """Explicit list of autostart-capable transports; ZT absent."""
    m = re.search(r"AUTOSTART_TRANSPORTS\s*=\s*\[([^\]]+)\]", js_text)
    assert m, "AUTOSTART_TRANSPORTS constant missing"
    body = m.group(1)
    assert '"tailscale"' in body
    assert '"cloudflared"' in body
    assert '"ngrok"' in body
    assert '"zerotier"' not in body


def test_js_loader_fetches_autostart_endpoint(js_text: str):
    assert 'window.api("/v1/autostart")' in js_text


def test_js_transportAutostartToggle_exported(js_text: str):
    assert "window.transportAutostartToggle" in js_text
    assert "transportAutostartToggle" in js_text


def test_js_toggle_posts_json_with_enabled(js_text: str):
    """POST body must be {"enabled": <bool>} -- matches the
    handler's request.json() contract."""
    # Locate the toggle function body.
    m = re.search(r"async function transportAutostartToggle.*?(?=window\.transportAutostartToggle)",
                  js_text, flags=re.DOTALL)
    assert m
    body = m.group(0)
    assert 'method: "POST"' in body
    assert 'JSON.stringify({enabled: !!enabled})' in body


def test_js_render_reads_env_override_and_marker(js_text: str):
    """_renderAutostart flips box.disabled when env_override is
    true, so the operator sees the checkbox as read-only."""
    m = re.search(r"function _renderAutostart.*?(?=async function transportAutostartToggle)",
                  js_text, flags=re.DOTALL)
    assert m
    body = m.group(0)
    assert "state.env_override" in body
    assert "box.disabled" in body
    # And the pill toggle:
    assert 'envPill.classList.add("on")' in body
    assert 'envPill.classList.remove("on")' in body


def test_js_toggle_handles_env_override_warning(js_text: str):
    """When the handler returns env_override_warning, the JS
    surfaces it in the hint area rather than swallowing it."""
    assert "env_override_warning" in js_text
