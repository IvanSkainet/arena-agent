"""Tests for v3.84.2: screen recording + apk upload."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# recording — settings validation
# ---------------------------------------------------------------------------
def test_record_sync_rejects_out_of_range_duration(monkeypatch):
    from arena.mobile import recording as _r
    monkeypatch.setattr(_r, "find_adb", lambda: "/usr/bin/adb")
    for bad in (0, 100, 200_000):
        result = _r.record_sync("dummy", duration_ms=bad)
        assert result["ok"] is False
        assert "duration_ms" in result["error"]


def test_record_sync_rejects_bad_size(monkeypatch):
    from arena.mobile import recording as _r
    monkeypatch.setattr(_r, "find_adb", lambda: "/usr/bin/adb")
    for bad in ("", "720", "720x", "not-a-size", "720X1600"):
        result = _r.record_sync("dummy", duration_ms=2000, size=bad)
        assert result["ok"] is False
        assert "size" in result["error"]


def test_record_sync_rejects_out_of_range_bitrate(monkeypatch):
    from arena.mobile import recording as _r
    monkeypatch.setattr(_r, "find_adb", lambda: "/usr/bin/adb")
    for bad in (0, 50_000, 500_000_000):
        result = _r.record_sync("dummy", duration_ms=2000, bit_rate=bad)
        assert result["ok"] is False
        assert "bit_rate" in result["error"]


def test_record_sync_needs_adb(monkeypatch):
    from arena.mobile import recording as _r
    monkeypatch.setattr(_r, "find_adb", lambda: None)
    r = _r.record_sync("dummy", duration_ms=2000)
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


# ---------------------------------------------------------------------------
# recording — full sync flow with mocked adb
# ---------------------------------------------------------------------------
def test_record_sync_success_shape(monkeypatch):
    """Full sync flow: mkdir → screenrecord → stat → cat → rm.
    Every adb call is mocked; we assert on the request shape."""
    from arena.mobile import recording as _r
    monkeypatch.setattr(_r, "find_adb", lambda: "/usr/bin/adb")

    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200
    calls = []

    def _fake_run(args, serial=None, timeout=None, capture_binary=False):
        calls.append(list(args))
        result = MagicMock()
        result.returncode = 0
        result.stderr = b"" if capture_binary else ""
        # Route by command shape
        joined = " ".join(str(a) for a in args)
        if "mkdir" in joined:
            result.stdout = "" if not capture_binary else b""
        elif "screenrecord" in joined:
            result.stdout = ""
        elif "stat" in joined:
            result.stdout = str(len(fake_mp4))
        elif "exec-out" in joined and "cat" in joined:
            result.stdout = fake_mp4
        elif joined.startswith("shell rm"):
            result.stdout = ""
        else:
            result.stdout = "" if not capture_binary else b""
        return result

    monkeypatch.setattr(_r, "run", _fake_run)

    r = _r.record_sync("2200ad3b", duration_ms=2000, size="720x1600",
                       bit_rate=4_000_000, include_bytes=True,
                       keep_on_device=False)
    assert r["ok"] is True
    assert r["action"] == "record_sync"
    assert r["remote_path"].startswith("/sdcard/DCIM/ArenaRecordings/sync-")
    assert r["size_bytes"] == len(fake_mp4)
    assert r["mime"] == "video/mp4"
    assert r["bytes_b64"]
    assert r["cleaned_up"] is True
    # Verify screenrecord got the right flags.
    sr_call = next(c for c in calls if "screenrecord" in " ".join(str(a) for a in c))
    assert "--time-limit" in sr_call and "2" in sr_call
    assert "--size" in sr_call and "720x1600" in sr_call
    assert "--bit-rate" in sr_call and "4000000" in sr_call


def test_record_sync_reports_empty_file(monkeypatch):
    """If screenrecord produced no output (permission, etc), we surface
    a clear error instead of a broken base64 blob."""
    from arena.mobile import recording as _r
    monkeypatch.setattr(_r, "find_adb", lambda: "/usr/bin/adb")

    def _fake_run(args, serial=None, timeout=None, capture_binary=False):
        result = MagicMock()
        result.returncode = 0
        result.stderr = "" if not capture_binary else b""
        joined = " ".join(str(a) for a in args)
        if "stat" in joined:
            result.stdout = "0"
        else:
            result.stdout = "" if not capture_binary else b""
        return result
    monkeypatch.setattr(_r, "run", _fake_run)

    r = _r.record_sync("dummy", duration_ms=2000)
    assert r["ok"] is False
    assert "did not land" in r["error"]


# ---------------------------------------------------------------------------
# recording — async registry lifecycle
# ---------------------------------------------------------------------------
def test_async_recording_lifecycle(monkeypatch):
    """start → list → stop → pull round-trip using the module registry."""
    from arena.mobile import recording as _r
    monkeypatch.setattr(_r, "find_adb", lambda: "/usr/bin/adb")
    # Wipe registry between tests.
    _r._REGISTRY.clear()

    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 500

    def _fake_run(args, serial=None, timeout=None, capture_binary=False):
        result = MagicMock()
        result.returncode = 0
        result.stderr = "" if not capture_binary else b""
        joined = " ".join(str(a) for a in args)
        if "mkdir" in joined:
            result.stdout = ""
        elif "sh -c" in joined and "screenrecord" in joined:
            # spawn — the registry then reads back the PID file
            result.stdout = ""
        elif "cat" in joined and ".pid" in joined:
            result.stdout = "42"
        elif "stat" in joined:
            result.stdout = str(len(fake_mp4))
        elif "kill" in joined:
            result.stdout = ""
        elif "exec-out" in joined and "cat" in joined:
            result.stdout = fake_mp4
        else:
            result.stdout = "" if not capture_binary else b""
        return result
    monkeypatch.setattr(_r, "run", _fake_run)

    started = _r.start_async("2200ad3b", duration_ms=10_000)
    assert started["ok"] is True
    rec_id = started["id"]
    assert started["pid"] == 42
    assert started["status"] == "running"

    listed = _r.list_recordings("2200ad3b")
    assert listed["ok"] is True
    assert listed["count"] == 1
    assert listed["recordings"][0]["id"] == rec_id

    stopped = _r.stop_async(rec_id)
    assert stopped["ok"] is True
    assert stopped["size_bytes"] == len(fake_mp4)

    pulled = _r.pull_recording(rec_id)
    assert pulled["ok"] is True
    assert pulled["mime"] == "video/mp4"
    assert pulled["bytes_b64"]


def test_stop_unknown_recording_id_returns_error():
    from arena.mobile import recording as _r
    _r._REGISTRY.clear()
    r = _r.stop_async("does-not-exist")
    assert r["ok"] is False
    assert "unknown" in r["error"]


# ---------------------------------------------------------------------------
# apk_install.save_upload — the new upload path
# ---------------------------------------------------------------------------
def test_apk_save_upload_rejects_traversal(tmp_path, monkeypatch):
    from arena.mobile import apk_install as _apk
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    # Any `..` segment must be refused before the ZIP magic check.
    for bad in ("../etc/passwd", "sub/../../evil.apk", "..", ""):
        r = _apk.save_upload(bad, b"PK\x03\x04" + b"\x00" * 500)
        assert r["ok"] is False, f"{bad!r} should be refused"


def test_apk_save_upload_rejects_non_zip_magic(tmp_path, monkeypatch):
    from arena.mobile import apk_install as _apk
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    r = _apk.save_upload("evil.apk", b"MZ\x00\x00" + b"\x00" * 500)
    assert r["ok"] is False
    assert "PK" in r["error"] or "APK" in r["error"] or "ZIP" in r["error"]


def test_apk_save_upload_rejects_tiny_file(tmp_path, monkeypatch):
    from arena.mobile import apk_install as _apk
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    r = _apk.save_upload("stub.apk", b"PK\x03\x04")   # 4 bytes
    assert r["ok"] is False


def test_apk_save_upload_writes_file_and_chains_to_prepare(tmp_path, monkeypatch):
    """Happy path: writes bytes to staging + returns sha + consent."""
    import hashlib
    import zipfile
    import io as _io
    from arena.mobile import apk_install as _apk
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    # Build a minimum ZIP-shaped payload.
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x00\x00hello\x00\x00")
        z.writestr("classes.dex", b"dex\n" + b"\x00" * 200)
    payload = buf.getvalue()

    r = _apk.save_upload("sub/uploaded.apk", payload)
    assert r["ok"] is True
    dest = tmp_path / "sub" / "uploaded.apk"
    assert dest.exists()
    assert dest.read_bytes() == payload
    assert r["sha256"] == hashlib.sha256(payload).hexdigest()
    assert r["required_consent"].startswith("yes-install-")
    assert r["written_bytes"] == len(payload)
    assert r["action"] == "apk_upload"


# ---------------------------------------------------------------------------
# Handler dataclass — v3.84.2 field surface
# ---------------------------------------------------------------------------
def test_mobile_handlers_dataclass_fields_v84_2():
    from arena.mobile.handlers import MobileHandlers
    expected = {
        "list_devices", "device_info", "screenshot", "tap", "swipe",
        "type_text", "key_event", "shell", "packages", "gesture",
        "ui_dump", "tap_by",
        "helpers_status", "helpers_install",
        "ime_status", "ime_set", "ime_reset", "paste",
        "sensors", "scroll", "key_combo",
        "pair", "connect", "disconnect", "apk_prepare", "apk_install",
        "batch",
        "camera_launch", "camera_shutter", "camera_photos",
        "camera_pull", "camera_capture",
        # v3.84.2
        "apk_upload",
        "record_sync", "record_start", "record_stop",
        "record_list", "record_pull", "record_purge",
    }
    got = {f.name for f in MobileHandlers.__dataclass_fields__.values()}
    assert expected == got, f"MobileHandlers fields drift: {got - expected} / {expected - got}"


# ---------------------------------------------------------------------------
# CLI subparser wiring
# ---------------------------------------------------------------------------
def test_cli_has_v84_2_subcommands():
    import importlib.util
    from importlib.machinery import SourceFileLoader
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    cli_path = root / "bin" / "arena-mobile"
    if not cli_path.exists():
        pytest.skip("bin/arena-mobile not in this checkout")
    loader = SourceFileLoader("arena_mobile_cli", str(cli_path))
    spec = importlib.util.spec_from_loader("arena_mobile_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    parser = mod.build_parser()
    sub_actions = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
    got = set(sub_actions[0].choices.keys())
    for name in ("apk-upload", "record", "recordings"):
        assert name in got, f"{name!r} missing from CLI"
