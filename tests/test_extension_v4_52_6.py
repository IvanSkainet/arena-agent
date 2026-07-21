"""v0.14.42 / v4.52.6 tests: Scan Now tab picker + auto-inject.

Full DOM behaviour verified in jstest/smoke_v526.js.
"""
from __future__ import annotations

import json
from pathlib import Path
from tests._version_matrix import any_bridge_in, any_pyproject_in

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(CHAT_EXT / "manifest.json"))["version"] in ("0.14.42",)


def test_content_script_version_bumped():
    assert "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';" in _read(CHAT_EXT / "content.js")


def test_insert_strategies_version_bumped():
    assert "return '0.14.42';" in _read(CHAT_EXT / "insert_strategies.js")


def test_readme_mentions_v4_52_6():
    src = _read(CHAT_EXT / "README.md")
    assert "0.14.42" in src
    assert ("v4.52.6" in src or "v4.53.0" in src or "v4.53.1" in src)


def test_constants_version_bumped():
    assert any_bridge_in(_read(REPO_ROOT / 'arena' / 'constants.py'))


def test_pyproject_version_bumped():
    assert any_pyproject_in(_read(REPO_ROOT / 'pyproject.toml'))


# ------------------------------------------------------------------
# Background: auto-inject fallback
# ------------------------------------------------------------------

def test_background_has_content_script_files_constant():
    src = _read(CHAT_EXT / "background.js")
    assert "ARENA_CONTENT_SCRIPT_FILES" in src


def test_background_content_script_files_match_manifest():
    """The programmatic-inject file list MUST match
    manifest.json content_scripts[0].js byte-for-byte order --
    otherwise auto-inject on old tabs will fail differently
    from Chrome's built-in inject."""
    bg = _read(CHAT_EXT / "background.js")
    manifest = json.loads(_read(CHAT_EXT / "manifest.json"))
    manifest_files = manifest["content_scripts"][0]["js"]

    # Extract the array literal from background.js.
    import re
    m = re.search(
        r"const ARENA_CONTENT_SCRIPT_FILES = \[(.+?)\];",
        bg, flags=re.DOTALL,
    )
    assert m, "ARENA_CONTENT_SCRIPT_FILES not parseable"
    bg_files = re.findall(r"'([^']+)'", m.group(1))
    assert bg_files == manifest_files, (
        f"drift between background.js ARENA_CONTENT_SCRIPT_FILES "
        f"({bg_files}) and manifest.json content_scripts.js ({manifest_files})"
    )


def test_background_uses_scripting_executeScript():
    src = _read(CHAT_EXT / "background.js")
    assert "chrome.scripting.executeScript" in src or "chrome.scripting?.executeScript" in src
    assert "_arenaInjectContentScriptsInto" in src


def test_background_retries_on_receiving_end_error():
    """The retry-with-inject must be gated on the specific
    Chrome error class AND on the target being a supported
    host. Do not retry on random errors -- do not attempt to
    inject on unsupported sites."""
    src = _read(CHAT_EXT / "background.js")
    assert "Receiving end does not exist|Could not establish" in src
    assert "_arenaIsSupportedChatHost" in src
    assert "_auto_injected" in src


def test_background_send_specific_tab_helper_present():
    src = _read(CHAT_EXT / "background.js")
    assert "_arenaSendToSpecificTab" in src
    # Explicit tabId override takes precedence over ranker.
    assert "Number.isInteger(opts.tabId)" in src


# ------------------------------------------------------------------
# Background: new message handlers
# ------------------------------------------------------------------

def test_background_registers_listSupportedTabs_handler():
    src = _read(CHAT_EXT / "background.js")
    assert "arena.listSupportedTabs" in src
    assert "listSupportedChatTabs" in src


def test_background_registers_injectContentScripts_handler():
    src = _read(CHAT_EXT / "background.js")
    assert "arena.injectContentScripts" in src


def test_background_scanPage_accepts_body_tabId():
    """arena.scanPage must forward `body` (containing an
    optional `tabId`) to scanActivePage so the picker can
    override the auto-ranker."""
    src = _read(CHAT_EXT / "background.js")
    # scanActivePage receives opts and passes to sendActiveTabMessage.
    assert "scanActivePage(message.body || {})" in src


# ------------------------------------------------------------------
# Sidepanel HTML: picker controls
# ------------------------------------------------------------------

def test_sidepanel_html_has_tab_picker():
    html = _read(CHAT_EXT / "sidepanel.html")
    for eid in ("scanTabPicker", "scanTabReloadBtn", "scanTabHint"):
        assert f'id="{eid}"' in html, f"missing picker element: {eid}"


def test_sidepanel_picker_has_auto_option():
    html = _read(CHAT_EXT / "sidepanel.html")
    assert 'value="__auto__"' in html
    assert "highest-ranked supported tab" in html


# ------------------------------------------------------------------
# Sidepanel JS: picker refresh + tabId body
# ------------------------------------------------------------------

def test_sidepanel_has_refreshScanTabPicker():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "refreshScanTabPicker" in src
    # Picker refresh is wired both into TAB_LOAD_HOOKS.status
    # and into the general refreshAll flow.
    assert "TAB_LOAD_HOOKS.status" in src
    assert "refreshScanTabPicker()" in src


def test_sidepanel_scan_now_sends_tabId_when_picked():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "arena.listSupportedTabs" in src
    # Body only carries tabId when a specific option is picked.
    assert "tabId: parseInt(pickerVal, 10)" in src or "tabId: Number(pickerVal)" in src


def test_sidepanel_renders_auto_injected_badge():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "_auto_injected" in src
    assert "auto-injected" in src


def test_sidepanel_lists_supported_sites_on_empty_tabs():
    src = _read(CHAT_EXT / "sidepanel.js")
    # When no supported tab is open, the hint must list at
    # least the flagship sites.
    for named in ("ChatGPT", "Claude", "Gemini", "Qwen", "DeepSeek"):
        assert named in src, f"picker hint should name {named}"


# ------------------------------------------------------------------
# CSS
# ------------------------------------------------------------------

def test_popup_css_has_scan_controls_style():
    css = _read(CHAT_EXT / "popup.css")
    assert ".arena-scan-controls" in css
