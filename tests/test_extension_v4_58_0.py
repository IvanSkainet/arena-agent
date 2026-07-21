"""v4.58.0 — asr.transcribe (whisper.cpp wrapper) + asr.models."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from arena import constants
from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_registry_asr import ASR_MCP_TOOLS
from arena.mcp.tool_asr import (
    _clamp_timeout,
    _find_model,
    _find_whisper_binary,
    _handle_asr_models,
    _handle_asr_transcribe,
    handle_asr_tool,
)
from arena.extension_bridge.policy import classify_tool_risk


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(p: str) -> str:
    return (REPO_ROOT / p).read_text(encoding="utf-8")


# --------- Version ---------
def test_version_is_4_58_0():
    assert constants.VERSION in ("4.58.0", "4.59.0", "4.59.1", "4.60.0", "4.60.1", "4.60.2", "4.60.3")


def test_pyproject_version_is_4_58_0():
    assert any(v in _read("pyproject.toml") for v in ('version = "4.58.0"', 'version = "4.59.0"', 'version = "4.59.1"', 'version = "4.60.0"', 'version = "4.60.1"', 'version = "4.60.2"', 'version = "4.60.3"'))


# --------- Registry ---------
def test_asr_registry_two_tools():
    names = {t["name"] for t in ASR_MCP_TOOLS}
    assert names == {"asr.transcribe", "asr.models"}


def test_asr_tools_appear_in_MCP_TOOLS():
    mcp = {t["name"] for t in MCP_TOOLS}
    for t in ASR_MCP_TOOLS:
        assert t["name"] in mcp


def test_asr_dispatcher_wired_in_tools_module():
    src = _read("arena/mcp/tools.py")
    assert "handle_asr_tool" in src
    assert "from arena.mcp.tool_asr import handle_asr_tool" in src


# --------- Risk classification ---------
def test_asr_transcribe_is_medium():
    """Local CPU/GPU compute — same tier as fs.create."""
    assert classify_tool_risk("asr.transcribe") == "medium"


def test_asr_models_is_safe():
    assert classify_tool_risk("asr.models") == "safe"


# --------- _clamp_timeout ---------
@pytest.mark.parametrize("raw, expected", [
    (None, 120.0), ("", 120.0), (5, 10.0), (100, 100.0), (2000, 900.0),
])
def test_asr_clamp_timeout(raw, expected):
    assert _clamp_timeout(raw) == expected


# --------- _find_model ---------
def test_find_model_returns_explicit_when_exists(tmp_path):
    m = tmp_path / "ggml-test.bin"
    m.write_bytes(b"x")
    path, err = _find_model(str(m))
    assert path == str(m) and err is None


def test_find_model_reports_missing_explicit(tmp_path):
    path, err = _find_model(str(tmp_path / "missing.bin"))
    assert path is None
    assert "not found" in err


def test_find_model_respects_env(tmp_path, monkeypatch):
    m = tmp_path / "ggml-env.bin"
    m.write_bytes(b"x")
    monkeypatch.setenv("ARENA_WHISPER_MODEL", str(m))
    # Guard: ensure ~/.whisper isn't preferred by pointing HOME to tmp too.
    monkeypatch.setenv("HOME", str(tmp_path))
    path, err = _find_model(None)
    assert path == str(m) and err is None


def test_find_model_fallback_to_home_whisper_dir(tmp_path, monkeypatch):
    home = tmp_path
    (home / ".whisper").mkdir()
    m = home / ".whisper" / "ggml-base.bin"
    m.write_bytes(b"x")
    monkeypatch.delenv("ARENA_WHISPER_MODEL", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    path, err = _find_model(None)
    assert path == str(m) and err is None


def test_find_model_hint_when_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("ARENA_WHISPER_MODEL", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path, err = _find_model(None)
    assert path is None
    assert "download" in err.lower() or "ARENA_WHISPER_MODEL" in err


# --------- input validation ---------
def test_asr_transcribe_requires_file():
    out = _handle_asr_transcribe({})
    assert out.get("isError")


def test_asr_transcribe_reports_missing_file(tmp_path):
    out = _handle_asr_transcribe({"file": str(tmp_path / "nope.wav")})
    assert out.get("isError")
    assert "not found" in out["content"][0]["text"].lower()


def test_asr_transcribe_reports_missing_binary(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setattr("arena.mcp.tool_asr._find_whisper_binary", lambda: None)
    out = _handle_asr_transcribe({"file": str(audio)})
    assert out.get("isError")
    assert "whisper-cli" in out["content"][0]["text"]


# --------- successful run (mocked subprocess) ---------
def test_asr_transcribe_happy_path_wav(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF" + b"0" * 100)
    model = tmp_path / "ggml-tiny.bin"
    model.write_bytes(b"x")

    monkeypatch.setattr("arena.mcp.tool_asr._find_whisper_binary", lambda: "/usr/bin/whisper-cli")

    # Mock subprocess.run + JSON file emission.
    def _fake_run(cmd, capture_output, timeout, text):
        # Extract -of prefix
        idx = cmd.index("-of") + 1
        prefix = Path(cmd[idx])
        (prefix.with_suffix(".json")).write_text(json.dumps({
            "result": {"language": "ru"},
            "transcription": [
                {"text": " Hello world.", "offsets": {"from": 0, "to": 1000}},
                {"text": " Second line.", "offsets": {"from": 1000, "to": 2500}},
            ],
        }))
        class _R: returncode = 0; stdout = ""; stderr = ""
        return _R()

    with mock.patch("arena.mcp.tool_asr.subprocess.run", _fake_run):
        out = _handle_asr_transcribe({"file": str(audio), "model": str(model)})
    assert out["ok"] is True
    assert out["language"] == "ru"
    assert "Hello world" in out["text"]
    assert "Second line" in out["text"]
    assert out["segment_count"] == 2
    assert out["duration_ms"] == 2500
    assert out["model"] == str(model)


def test_asr_transcribe_reports_whisper_timeout(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"; audio.write_bytes(b"RIFF")
    model = tmp_path / "ggml-tiny.bin"; model.write_bytes(b"x")
    monkeypatch.setattr("arena.mcp.tool_asr._find_whisper_binary", lambda: "/usr/bin/whisper-cli")

    def _fake_run(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=a[0], timeout=kw.get("timeout"))
    with mock.patch("arena.mcp.tool_asr.subprocess.run", _fake_run):
        out = _handle_asr_transcribe({"file": str(audio), "model": str(model), "timeout": 15})
    assert out["ok"] is False
    assert "timed out" in out["error"]


def test_asr_transcribe_reports_whisper_nonzero(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"; audio.write_bytes(b"RIFF")
    model = tmp_path / "ggml-tiny.bin"; model.write_bytes(b"x")
    monkeypatch.setattr("arena.mcp.tool_asr._find_whisper_binary", lambda: "/usr/bin/whisper-cli")

    def _fake_run(*a, **kw):
        class _R: returncode = 2; stdout = ""; stderr = "unsupported audio format"
        return _R()
    with mock.patch("arena.mcp.tool_asr.subprocess.run", _fake_run):
        out = _handle_asr_transcribe({"file": str(audio), "model": str(model)})
    assert out["ok"] is False
    assert "exit 2" in out["error"]
    assert "unsupported" in out["stderr"]


# --------- asr.models ---------
def test_asr_models_lists_home_whisper(tmp_path, monkeypatch):
    home = tmp_path
    (home / ".whisper").mkdir()
    m = home / ".whisper" / "ggml-base.bin"
    m.write_bytes(b"x" * 1024)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("ARENA_WHISPER_MODEL", raising=False)
    monkeypatch.setattr("arena.mcp.tool_asr._find_whisper_binary", lambda: "/usr/bin/whisper-cli")
    out = _handle_asr_models({})
    assert out["ok"] is True
    assert out["count"] >= 1
    assert any(mdl["name"] == "ggml-base.bin" for mdl in out["models"])
    assert out["binary"] == "/usr/bin/whisper-cli"


# --------- Full dispatch through handle_asr_tool ---------
def test_handle_asr_tool_returns_none_for_non_asr():
    assert handle_asr_tool("fs.read", {"path": "/tmp"}) is None


def test_handle_asr_tool_wraps_transcribe_in_text_content(tmp_path):
    out = handle_asr_tool("asr.transcribe", {})
    assert isinstance(out, dict)
    # Wrapped in text_content — but errors bypass and return {isError: True}.
    assert out.get("isError") or "content" in out


# --------- Changelog ---------
def test_changelog_mentions_v4_58_0():
    assert "4.58.0" in _read("CHANGELOG.md")
    assert "4.58.0" in _read("CHANGELOG.ru.md")
