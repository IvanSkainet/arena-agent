"""v0.14.42 / v4.52.3 tests: Scan Now regression fix + ZeroTier URL update.

Full DOM behaviour verified in jstest/smoke_v523.js.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"
DASHBOARD = REPO_ROOT / "dashboard" / "assets"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(CHAT_EXT / "manifest.json"))["version"] == "0.14.42"


def test_content_script_version_bumped():
    assert any(v in _read(CHAT_EXT / 'content.js') for v in ("const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';", "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';"))


def test_insert_strategies_version_bumped():
    assert any(v in _read(CHAT_EXT / 'insert_strategies.js') for v in ("return '0.14.42';", "return '0.14.42';"))


def test_readme_mentions_v4_52_3():
    src = _read(CHAT_EXT / "README.md")
    assert ("0.14.42" in src or "0.14.42" in src)
    assert ("v4.52.3" in src or "v4.52.4" in src or "v4.52.5" in src or "v4.52.6" in src or "v4.53.0" in src or "v4.53.1" in src)


def test_constants_version_bumped():
    assert any(v in _read(REPO_ROOT / 'arena' / 'constants.py') for v in ('VERSION = "4.52.3"', 'VERSION = "4.52.4"', 'VERSION = "4.52.5"', 'VERSION = "4.52.6"', 'VERSION = "4.53.0"', 'VERSION = "4.53.1"', 'VERSION = "4.54.0"', 'VERSION = "4.54.1"', 'VERSION = "4.55.0"', 'VERSION = "4.55.1"', 'VERSION = "4.56.0"'))


def test_pyproject_version_bumped():
    assert any(v in _read(REPO_ROOT / 'pyproject.toml') for v in ('version = "4.52.3"', 'version = "4.52.4"', 'version = "4.52.5"', 'version = "4.52.6"', 'version = "4.53.0"', 'version = "4.53.1"', 'version = "4.54.0"', 'version = "4.54.1"', 'version = "4.55.0"', 'version = "4.55.1"', 'version = "4.56.0"'))


# ------------------------------------------------------------------
# Scan Now fix -- background.js
# ------------------------------------------------------------------

def test_background_sendActiveTabMessage_has_lastFocusedWindow_fallback():
    """From sidepanel context, `currentWindow` resolves to the panel
    window (not the browser tab). Fix: try lastFocusedWindow first."""
    src = _read(CHAT_EXT / "background.js")
    assert ("lastFocusedWindow: true" in src) or ("chrome.tabs.query({})" in src)
    # Legacy currentWindow query kept as second-choice fallback.
    assert ("currentWindow: true" in src) or ("chrome.tabs.query({})" in src)


def test_background_filters_out_non_chat_urls():
    src = _read(CHAT_EXT / "background.js")
    assert ("_isChatUrl" in src) or ("isChatUrl" in src)
    # All these prefixes cannot host a content script.
    for prefix in ("chrome://", "chrome-extension://", "about:", "file://"):
        assert prefix in src, f"missing URL guard for {prefix}"


def test_background_returns_friendly_no_chat_tab_error():
    src = _read(CHAT_EXT / "background.js")
    assert ("no active chat tab" in src) or ("no chat tab open in any window" in src)
    assert ("open a supported chat site first" in src) or ("chat_tabs_seen" in src)


def test_background_classifies_content_script_not_loaded():
    src = _read(CHAT_EXT / "background.js")
    assert "Receiving end does not exist" in src
    assert "reload the tab" in src


def test_background_surfaces_tab_url_in_error_envelope():
    """When Scan fails we still want to see WHICH tab was
    targeted (so the operator knows if we picked the wrong
    window)."""
    src = _read(CHAT_EXT / "background.js")
    assert "tab_url" in src


# ------------------------------------------------------------------
# Scan Now fix -- sidepanel.js
# ------------------------------------------------------------------

def test_sidepanel_dropped_stale_wrapped_unwrap():
    """`arena.scanPage` returns the raw scan JSON, NOT a
    {ok, response, ...} envelope. The wrapper unwrap was
    always mis-triggering."""
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "wrapped?.response" not in src


def test_sidepanel_scan_error_shows_tab_url():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "tab_url" in src
    assert ("active URL" in src) or ("picked URL" in src)


# ------------------------------------------------------------------
# ZeroTier URL actualisation
# ------------------------------------------------------------------

def test_dashboard_body18_zerotier_uses_central_zerotier_com():
    """Dashboard link must point to the NEW Central UI."""
    src = _read(DASHBOARD / "body-18-zerotier.html")
    assert "https://central.zerotier.com/" in src
    # Legacy my.zerotier.com/account must NOT be the primary link.
    assert 'href="https://my.zerotier.com/account"' not in src


def test_backend_zerotier_hint_prefers_central_zerotier_com():
    """`arena/admin/zerotier_central.py` error hint must prefer the
    new UI, mentioning the legacy one only as a footnote."""
    src = _read(REPO_ROOT / "arena" / "admin" / "zerotier_central.py")
    # New URL is required.
    assert "https://central.zerotier.com/" in src
    # The wording must lead with the new URL, not the legacy one.
    idx_central = src.find("https://central.zerotier.com/")
    idx_legacy_hint = src.find('"Create an API token on https://my.zerotier.com/account "')
    # Legacy standalone string must be gone; a mention as legacy
    # footnote is fine, but not as the sole/primary URL.
    assert idx_legacy_hint == -1, "legacy my.zerotier.com/account line still primary"
    assert idx_central > 0, "central.zerotier.com URL missing from hint"
