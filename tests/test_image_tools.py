"""v4.87.0 — image.* OCR preprocessing tools."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk
from arena.image import preprocess as ip
from arena.mcp.tool_image import handle_image_tool
from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_registry_image import IMAGE_MCP_TOOLS


def test_image_registry_and_policy():
    names = {t["name"] for t in IMAGE_MCP_TOOLS}
    assert names == {"image.health", "image.preprocess_for_ocr"}
    assert names <= {t["name"] for t in MCP_TOOLS}
    assert classify_tool_risk("image.health") == "safe"
    assert classify_tool_risk("image.preprocess_for_ocr") == "medium"


def test_image_health_reports_pillow():
    h = ip.image_health()
    assert "pillow" in h
    assert "opencv" in h
    assert h["pillow"]["ok"] is True


def test_default_output_path_lands_in_ocr_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_IMAGE_DIR", str(tmp_path / "out"))
    p = ip.default_output_path(tmp_path / "doc.jpg")
    assert p.parent == tmp_path / "out"
    assert p.name.startswith("doc.ocr-") and p.suffix == ".png"


def test_preprocess_for_ocr_creates_png(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    src = tmp_path / "doc.jpg"
    Image.new("RGB", (300, 200), color=(230, 230, 230)).save(src)
    out = tmp_path / "out.png"
    r = ip.preprocess_for_ocr(src, output=out, max_size=100, threshold=True, deskew=False)
    assert r["ok"] is True
    assert r["output"] == str(out)
    assert out.is_file()
    assert max(r["width"], r["height"]) == 100
    assert "grayscale" in r["steps"]
    assert any(s.startswith("resize:") for s in r["steps"])
    assert any(s.startswith("threshold:") for s in r["steps"])


def test_handle_image_tool_preprocess_wraps_content(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    src = tmp_path / "doc.jpg"
    Image.new("RGB", (50, 50), color=(255, 255, 255)).save(src)
    out = handle_image_tool("image.preprocess_for_ocr", {"file": str(src), "max_size": 50})
    assert out and "content" in out
    parsed = json.loads(out["content"][0]["text"])
    assert parsed["ok"] is True
    assert Path(parsed["output"]).is_file()


def test_handle_image_tool_none_for_other():
    assert handle_image_tool("ocr.extract", {}) is None
