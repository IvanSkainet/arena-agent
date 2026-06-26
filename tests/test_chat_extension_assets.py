"""Chat extension scaffold regressions."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_extension_scaffold_exists():
    base = ROOT / "chat_extension"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    background = (base / "background.js").read_text(encoding="utf-8")
    content = (base / "content.js").read_text(encoding="utf-8")
    parser = (base / "parser.js").read_text(encoding="utf-8")
    adapter_sites = (base / "adapter_sites.js").read_text(encoding="utf-8")
    popup = (base / "popup.js").read_text(encoding="utf-8")
    popup_html = (base / "popup.html").read_text(encoding="utf-8")
    sidepanel = (base / "sidepanel.js").read_text(encoding="utf-8")
    sidepanel_html = (base / "sidepanel.html").read_text(encoding="utf-8")
    adapters = (base / "adapters.js").read_text(encoding="utf-8")
    readme = (base / "README.md").read_text(encoding="utf-8")
    assert manifest["manifest_version"] == 3
    assert "background.js" in manifest["background"]["service_worker"]
    assert manifest["version"] == "0.8.0"
    assert manifest["action"]["default_popup"] == "popup.html"
    assert manifest["side_panel"]["default_path"] == "sidepanel.html"
    assert manifest["content_scripts"][0]["js"][:4] == ["adapter_sites.js", "parser.js", "adapters.js", "settings.js"]
    assert "arena.preview" in background
    assert "arena.execute" in background
    assert "arena.testConnection" in background
    assert "arena.openSidePanel" in background
    assert "arena.replayHistory" in background
    assert "arena.clearHistory" in background
    assert "```arena-tool" in parser
    assert "```jsonl" in parser
    assert "function_call_start" in parser
    assert "Insert Result" in content
    assert "Insert & Submit" in content
    assert "Panel" in content
    assert "saveBtn" in popup_html
    assert "autoExecuteSafe" in popup_html
    assert "autoSubmitResult" in popup_html
    assert "panelBtn" in popup_html
    assert "clearBtn" in popup_html
    assert "arena.getConfig" in popup
    assert "arenaModeSummary" in popup
    assert "refreshBtn" in sidepanel_html
    assert "clearBtn" in sidepanel_html
    assert "runHistoryAction" in sidepanel
    assert "arenaInsertAndSubmit" in adapters
    assert "ARENA_SITE_ADAPTERS" in adapter_sites
    assert "chat.deepseek.com" in adapter_sites
    assert "kimi.com" in adapter_sites
    assert "chat.qwen.ai" in adapter_sites
    assert "arenaMessageFingerprint" in adapters
    assert "/v1/extension/execute" in readme
