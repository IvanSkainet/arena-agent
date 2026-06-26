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
    readme = (base / "README.md").read_text(encoding="utf-8")
    assert manifest["manifest_version"] == 3
    assert "background.js" in manifest["background"]["service_worker"]
    assert "arena.preview" in background
    assert "arena.execute" in background
    assert "```arena-tool" in content
    assert "/v1/extension/execute" in readme
