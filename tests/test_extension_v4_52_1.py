"""v0.14.35 / v4.52.1 tests: Settings tab + Scan Now viewer.

Front-end only. Full DOM/interaction behaviour is verified in
`jstest/smoke_settings.js` (23 jsdom assertions).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(CHAT_EXT / "manifest.json"))["version"] in ("0.14.35", "0.14.36", "0.14.42")


def test_content_script_version_bumped():
    assert any(v in _read(CHAT_EXT / 'content.js') for v in ("const ARENA_CONTENT_SCRIPT_VERSION = '0.14.35';", "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.36';", "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';"))


def test_insert_strategies_version_bumped():
    assert any(v in _read(CHAT_EXT / 'insert_strategies.js') for v in ("return '0.14.35';", "return '0.14.36';", "return '0.14.42';"))


def test_readme_mentions_v4_52_1():
    src = _read(CHAT_EXT / "README.md")
    assert ("0.14.35" in src or "0.14.36" in src or "0.14.42" in src)
    assert ("v4.52.1" in src or "v4.52.2" in src or "v4.52.3" in src or "v4.52.5" in src or "v4.52.6" in src or "v4.53.0" in src or "v4.53.1" in src)


def test_constants_version_bumped():
    assert any(v in _read(REPO_ROOT / 'arena' / 'constants.py') for v in ('VERSION = "4.52.1"', 'VERSION = "4.52.2"', 'VERSION = "4.52.3"', 'VERSION = "4.52.4"', 'VERSION = "4.52.5"', 'VERSION = "4.52.6"', 'VERSION = "4.53.0"', 'VERSION = "4.53.1"'))


def test_pyproject_version_bumped():
    assert any(v in _read(REPO_ROOT / 'pyproject.toml') for v in ('version = "4.52.1"', 'version = "4.52.2"', 'version = "4.52.3"', 'version = "4.52.4"', 'version = "4.52.5"', 'version = "4.52.6"', 'version = "4.53.0"', 'version = "4.53.1"'))


# ------------------------------------------------------------------
# Settings tab HTML
# ------------------------------------------------------------------

def test_sidepanel_has_five_tabs():
    html = _read(CHAT_EXT / "sidepanel.html")
    for tab in ("status", "tools", "instructions", "history", "settings"):
        assert f'data-tab="{tab}"' in html, f"missing tab: {tab}"
        assert f'id="tab-{tab}"' in html, f"missing tab panel: {tab}"


def test_settings_tab_has_bridge_inputs():
    html = _read(CHAT_EXT / "sidepanel.html")
    for eid in ("cfgBridgeUrl", "cfgBridgeToken",
                "cfgSaveBtn", "cfgRevealBtn", "cfgClearTokenBtn"):
        assert f'id="{eid}"' in html, f"missing settings control: {eid}"


def test_settings_tab_has_all_mode_toggles():
    html = _read(CHAT_EXT / "sidepanel.html")
    for eid in ("mAutoPreview", "mAutoExecuteSafe",
                "mAutoInsertResult", "mAutoSubmitResult",
                "mInsertStrategy", "mCollapseToolResults",
                "mDedupSemantic", "mEnableGenericAdapter",
                "mSaveBtn", "mResetBtn", "mSummary"):
        assert f'id="{eid}"' in html, f"missing settings toggle: {eid}"


def test_settings_tab_insert_strategy_options_full():
    """Insert strategy dropdown must expose every strategy the
    settings.js normaliser accepts (auto + 6 escapes)."""
    html = _read(CHAT_EXT / "sidepanel.html")
    for opt in ("auto", "nativeInsertText", "paragraphFallback",
                "pasteOnly", "directDomText", "directDomBlocks",
                "directDomPreWrap"):
        assert f'value="{opt}"' in html, f"missing insertStrategy option: {opt}"


def test_settings_tab_token_hint_calls_out_device_local():
    """Token security note must be present so users know the
    token is not synced across devices."""
    html = _read(CHAT_EXT / "sidepanel.html")
    assert "chrome.storage.local" in html
    assert "never leaves the device" in html


# ------------------------------------------------------------------
# Settings tab JS wiring
# ------------------------------------------------------------------

def test_sidepanel_js_registers_settings_loader():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "TAB_LOAD_HOOKS.settings" in src
    assert "loadSettings" in src
    assert "saveSettingsBridge" in src
    assert "saveSettingsModes" in src
    assert "resetSettingsModes" in src


def test_sidepanel_js_uses_getConfig_and_saveConfig():
    """Front-end must use the existing background message API
    (`arena.getConfig` / `arena.saveConfig`) -- do not invent a
    new one."""
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "arena.getConfig" in src
    assert "arena.saveConfig" in src


def test_sidepanel_js_settings_defaults_mirror_settings_js():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "ARENA_SETTINGS_DEFAULTS" in src
    # Must include every field settings.js normalises.
    for key in ("autoPreview", "autoExecuteSafe", "autoInsertResult",
                "autoSubmitResult", "insertStrategy", "dedupSemantic",
                "enableGenericAdapter", "collapseToolResults"):
        assert key in src, f"missing default field: {key}"


def test_sidepanel_js_toggle_fields_cover_all_boolean_modes():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "ARENA_TOGGLE_FIELDS" in src
    # Every boolean toggle must map an element id to a mode key.
    for pair in ("mAutoPreview", "mAutoExecuteSafe",
                 "mAutoInsertResult", "mAutoSubmitResult",
                 "mCollapseToolResults", "mDedupSemantic",
                 "mEnableGenericAdapter"):
        assert pair in src, f"missing toggle mapping: {pair}"


# ------------------------------------------------------------------
# Scan Now viewer
# ------------------------------------------------------------------

def test_status_tab_has_scan_now_controls():
    html = _read(CHAT_EXT / "sidepanel.html")
    for eid in ("scanNowBtn", "scanDetails", "scanSummary",
                "scanEvents", "scanRawBox"):
        assert f'id="{eid}"' in html, f"missing scan control: {eid}"


def test_sidepanel_js_scan_now_wiring():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "runScanNow" in src
    assert "arena.scanPage" in src
    # v4.52.3: the unwrap was wrong (arena.scanPage returns
    # raw scan JSON directly); we now check for the correct
    # error-envelope handling instead.
    assert "res?.ok === false" in src or "res.ok === false" in src or "wrapped?.response" in src
    # Must render events + raw JSON.
    assert "_sidepanelRenderScanEvents" in src
    assert "events_recent" in src


def test_sidepanel_js_scan_events_recognise_v4_51_4_diag_kinds():
    """Scan events pane must render the v4.51.4 diag fields
    (`target_kind`, `target_tag`, `lines`, `fingerprint`) so
    Ivan doesn't have to eyeball raw JSON to spot user-message
    vs code-fence collapse hits."""
    src = _read(CHAT_EXT / "sidepanel.js")
    for f in ("target_kind", "target_tag", "fingerprint",
              "previous_owner"):
        assert f in src, f"scan events renderer missing field: {f}"


# ------------------------------------------------------------------
# CSS
# ------------------------------------------------------------------

def test_popup_css_settings_and_scan_styles():
    css = _read(CHAT_EXT / "popup.css")
    for cls in (".arena-toggle", ".arena-hint", ".arena-btn-danger",
                ".arena-scan-details", ".arena-scan-summary",
                ".arena-scan-events", ".arena-scan-event",
                ".arena-scan-raw", ".arena-modes-summary"):
        assert cls in css, f"missing CSS class: {cls}"
