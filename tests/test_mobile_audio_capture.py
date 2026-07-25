"""v4.84.0 — unit tests for the mobile microphone-capture helpers.

These cover the pure logic in ``arena.mobile.audio_capture`` that does not
require adb or a device. The adb orchestration (install/record/pull) is
validated live. A key regression guard: the bundled recorder APK must
actually ship in ``assets/apks/`` or ``ensure_installed`` has nothing to
install.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mobile import audio_capture as ac


# ---------------------------------------------------------------------------
# pm_path_installed
# ---------------------------------------------------------------------------
def test_pm_path_installed_true():
    assert ac.pm_path_installed("package:/data/app/~~abc/com.arena.voicerecorder/base.apk") is True


def test_pm_path_installed_false_on_empty_or_error():
    assert ac.pm_path_installed("") is False
    assert ac.pm_path_installed("Error: not found") is False
    assert ac.pm_path_installed(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# parse_done_marker
# ---------------------------------------------------------------------------
def test_done_marker_ok():
    assert ac.parse_done_marker("ok") == (True, "")
    assert ac.parse_done_marker("  ok\n") == (True, "")


def test_done_marker_error():
    assert ac.parse_done_marker("error:no-permission") == (False, "no-permission")
    assert ac.parse_done_marker("error:IllegalStateException") == (False, "IllegalStateException")


def test_done_marker_unknown_is_failure():
    ok, detail = ac.parse_done_marker("")
    assert ok is False and detail == "unknown-marker"
    ok2, detail2 = ac.parse_done_marker("garbage")
    assert ok2 is False and detail2 == "garbage"


# ---------------------------------------------------------------------------
# default_output_path
# ---------------------------------------------------------------------------
def test_default_output_path_shape_and_determinism():
    p = ac.default_output_path(1784733561000)
    assert p == f"{ac.RECORD_DIR}/voice-1784733561000.m4a"
    assert p.endswith(".m4a")
    # Without an explicit epoch it still lands in the record dir.
    assert ac.default_output_path().startswith(ac.RECORD_DIR + "/")


# ---------------------------------------------------------------------------
# bundled_apk_path — the recorder APK must ship with the bridge
# ---------------------------------------------------------------------------
def test_bundled_apk_path_points_at_shipped_apk():
    apk = ac.bundled_apk_path()
    assert apk.name == ac.APK_NAME == "arena-voicerecorder.apk"
    assert apk.parent.name == "apks" and apk.parent.parent.name == "assets"
    assert apk.is_file(), f"bundled recorder APK missing at {apk}"
    # A real APK is a zip; check the PK magic so a truncated/empty file
    # can never silently ship as the recorder.
    assert apk.read_bytes()[:2] == b"PK"


# ---------------------------------------------------------------------------
# voice_capture_dir — honours the env override and is owner-only
# ---------------------------------------------------------------------------
def test_voice_capture_dir_uses_env_override(tmp_path, monkeypatch):
    target = tmp_path / "voice"
    monkeypatch.setenv("ARENA_VOICE_DIR", str(target))
    got = ac.voice_capture_dir()
    assert got == target
    assert target.is_dir()


# ---------------------------------------------------------------------------
# mobile.voice_record MCP wrapper argument wiring
# ---------------------------------------------------------------------------
def test_voice_record_wrapper_forwards_pre_delay(monkeypatch):
    from arena.mcp import tool_mobile_ext as ext

    captured = {}

    def fake_voice_record(serial, **kw):
        captured["serial"] = serial
        captured.update(kw)
        return {"ok": True}

    monkeypatch.setattr(ext._audio, "voice_record", fake_voice_record)
    out = ext._voice_record("serial-1", {
        "duration_ms": 12_000,
        "pre_delay_ms": 7_000,
        "return_bytes": True,
        "keep_on_device": True,
    })
    assert out == {"ok": True}
    assert captured == {
        "serial": "serial-1",
        "duration_ms": 12_000,
        "pre_delay_ms": 7_000,
        "return_bytes": True,
        "keep_on_device": True,
    }
