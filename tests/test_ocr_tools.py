"""v4.86.0 — generic ocr.* tools."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk
from arena.mcp.tool_ocr import (
    _find_tessdata_dir,
    _handle_ocr_bootstrap,
    _handle_ocr_extract,
    _handle_ocr_health,
    _langs,
    handle_ocr_tool,
)
from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_registry_ocr import OCR_MCP_TOOLS


def test_ocr_registry_and_mcp_tools():
    names = {t["name"] for t in OCR_MCP_TOOLS}
    assert names == {"ocr.health", "ocr.bootstrap", "ocr.extract", "ocr.extract_best"}
    all_names = {t["name"] for t in MCP_TOOLS}
    assert names <= all_names


def test_ocr_policy():
    assert classify_tool_risk("ocr.health") == "safe"
    assert classify_tool_risk("ocr.extract") == "medium"
    assert classify_tool_risk("ocr.extract_best") == "medium"
    assert classify_tool_risk("ocr.bootstrap") == "dangerous"


def test_langs_lists_traineddata(tmp_path):
    (tmp_path / "eng.traineddata").write_bytes(b"x")
    (tmp_path / "rus.traineddata").write_bytes(b"x")
    assert _langs(str(tmp_path)) == ["eng", "rus"]


def test_find_tessdata_next_to_binary(tmp_path):
    exe = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    tess = exe.parent / "tessdata"
    tess.mkdir(parents=True)
    exe.write_bytes(b"exe")
    assert _find_tessdata_dir(str(exe)) == str(tess)


def test_ocr_health_ok(tmp_path, monkeypatch):
    exe = tmp_path / "tesseract.exe"; exe.write_bytes(b"exe")
    tess = tmp_path / "tessdata"; tess.mkdir()
    (tess / "rus.traineddata").write_bytes(b"x")
    monkeypatch.setattr("arena.mcp.tool_ocr._find_tesseract", lambda: str(exe))
    monkeypatch.setattr("arena.mcp.tool_ocr._find_tessdata_dir", lambda binary=None: str(tess))
    out = _handle_ocr_health({})
    assert out["ok"] is True
    assert out["tesseract"] == str(exe)
    assert out["has_rus"] is True


def test_ocr_bootstrap_non_windows(monkeypatch):
    monkeypatch.setattr("arena.mcp.tool_ocr.platform.system", lambda: "Linux")
    out = _handle_ocr_bootstrap({})
    assert out["ok"] is False
    assert "Windows" in out["error"]


def test_ocr_extract_requires_file():
    out = _handle_ocr_extract({})
    assert out.get("isError")
    assert "missing" in out["content"][0]["text"].lower()


def test_ocr_extract_missing_file(tmp_path):
    out = _handle_ocr_extract({"file": str(tmp_path / "missing.png")})
    assert out.get("isError")
    assert "not found" in out["content"][0]["text"].lower()


def test_ocr_extract_happy_path(tmp_path, monkeypatch):
    img = tmp_path / "doc.png"; img.write_bytes(b"PNG")
    exe = tmp_path / "tesseract.exe"; exe.write_bytes(b"exe")
    tess = tmp_path / "tessdata"; tess.mkdir()
    monkeypatch.setattr("arena.mcp.tool_ocr._find_tesseract", lambda: str(exe))
    monkeypatch.setattr("arena.mcp.tool_ocr._find_tessdata_dir", lambda binary=None: str(tess))

    tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n" \
          "5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t95\tCoffee\n" \
          "5\t1\t1\t1\t1\t2\t50\t20\t20\t40\t90\ttomorrow\n"

    def fake_run(cmd, capture_output, text, timeout, env, **kwargs):
        assert cmd[0] == str(exe)
        assert cmd[-1] == "tsv"
        assert env.get("TESSDATA_PREFIX") == str(tess)
        class R:
            returncode = 0
            stdout = tsv
            stderr = ""
        return R()

    with mock.patch("arena.mcp.tool_ocr.subprocess.run", fake_run):
        out = _handle_ocr_extract({"file": str(img), "query": "coffee", "lang": "eng"})
    assert out["ok"] is True
    assert out["word_count"] == 2
    assert "Coffee" in out["text"]
    assert out["best_match"] is not None


def test_ocr_extract_nonzero(tmp_path, monkeypatch):
    img = tmp_path / "doc.png"; img.write_bytes(b"PNG")
    monkeypatch.setattr("arena.mcp.tool_ocr._find_tesseract", lambda: "/bin/tesseract")
    monkeypatch.setattr("arena.mcp.tool_ocr._find_tessdata_dir", lambda binary=None: None)

    def fake_run(*args, **kwargs):
        class R:
            returncode = 1
            stdout = ""
            stderr = "bad image"
        return R()

    with mock.patch("arena.mcp.tool_ocr.subprocess.run", fake_run):
        out = _handle_ocr_extract({"file": str(img)})
    assert out["ok"] is False
    assert "exit 1" in out["error"]


def test_handle_ocr_tool_wraps_content():
    out = handle_ocr_tool("ocr.health", {})
    assert isinstance(out, dict)
    assert "content" in out
    parsed = json.loads(out["content"][0]["text"])
    assert "ok" in parsed


def test_handle_ocr_tool_none_for_other():
    assert handle_ocr_tool("asr.health", {}) is None


def test_ocr_extract_with_preprocess_uses_output(tmp_path, monkeypatch):
    img = tmp_path / "doc.png"; img.write_bytes(b"PNG")
    pre = tmp_path / "doc.pre.png"; pre.write_bytes(b"PNG2")
    monkeypatch.setattr("arena.mcp.tool_ocr._find_tesseract", lambda: "/bin/tesseract")
    monkeypatch.setattr("arena.mcp.tool_ocr._find_tessdata_dir", lambda binary=None: None)
    monkeypatch.setattr("arena.mcp.tool_ocr.preprocess_for_ocr", lambda *a, **kw: {"ok": True, "output": str(pre), "steps": ["grayscale"]})

    tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n" \
          "5\t1\t1\t1\t1\t1\t1\t2\t3\t4\t90\tHello\n"

    def fake_run(cmd, capture_output, text, timeout, env, **kwargs):
        assert cmd[1] == str(pre)
        assert kwargs.get("encoding") == "utf-8"
        class R:
            returncode = 0
            stdout = tsv
            stderr = ""
        return R()

    with mock.patch("arena.mcp.tool_ocr.subprocess.run", fake_run):
        out = _handle_ocr_extract({"file": str(img), "preprocess": True})
    assert out["ok"] is True
    assert out["file"] == str(pre)
    assert out["preprocessed"]["output"] == str(pre)
    assert out["text"] == "Hello"


def test_ocr_score_penalises_garbage():
    from arena.mcp.tool_ocr import _score_ocr
    good = [
        {"text": "Hello", "confidence": 90},
        {"text": "world", "confidence": 90},
    ]
    noisy = [
        {"text": "|", "confidence": 90},
        {"text": "_", "confidence": 90},
    ]
    assert _score_ocr(good, "Hello world")["score"] > _score_ocr(noisy, "| _")["score"]


def test_ocr_extract_best_selects_highest_scoring_variant(tmp_path, monkeypatch):
    from arena.mcp import tool_ocr as mod

    img = tmp_path / "doc.png"; img.write_bytes(b"PNG")
    calls = []

    def fake_extract(args):
        calls.append(args)
        if args.get("preprocess"):
            return {
                "ok": True,
                "file": "pre.png",
                "psm": args.get("psm"),
                "word_count": 1,
                "words": [{"text": "|", "confidence": 10}],
                "text": "|",
                "preprocessed": {"steps": ["grayscale"]},
            }
        return {
            "ok": True,
            "file": str(img),
            "psm": args.get("psm"),
            "word_count": 3,
            "words": [
                {"text": "Buy", "confidence": 90},
                {"text": "coffee", "confidence": 90},
                {"text": "tomorrow", "confidence": 80},
            ],
            "text": "Buy coffee tomorrow",
            "preprocessed": None,
        }

    monkeypatch.setattr(mod, "_handle_ocr_extract", fake_extract)
    out = mod._handle_ocr_extract_best({"file": str(img), "max_variants": 3})
    assert out["ok"] is True
    assert out["selected_variant"].startswith("baseline")
    assert out["result"]["text"] == "Buy coffee tomorrow"
    assert len(out["variants"]) == 3
    assert calls[0]["file"] == str(img)


def test_handle_ocr_tool_extract_best_wraps_content(tmp_path, monkeypatch):
    from arena.mcp import tool_ocr as mod
    monkeypatch.setattr(mod, "_handle_ocr_extract_best", lambda args: {"ok": True, "selected_variant": "x"})
    out = mod.handle_ocr_tool("ocr.extract_best", {"file": "x.png"})
    parsed = json.loads(out["content"][0]["text"])
    assert parsed == {"ok": True, "selected_variant": "x"}
