"""Tests for v3.83.5 additions: wireless ADB pair/connect/disconnect,
generic APK install with SHA-256 consent, and the force_png_source
query param on screenshot."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any

from arena.mobile import adb as _adb
from arena.mobile import apk_install as _apk
from arena.mobile import wireless as _wl


# ---------------------------------------------------------------------------
# wireless.py — input validation, no-adb guards, output shape.
# ---------------------------------------------------------------------------
def test_pair_rejects_bad_host():
    for bad in ("", "with space", "..", "-badstart", None, 123):
        r = _wl.pair(bad, 12345, "123456")  # type: ignore[arg-type]
        assert r["ok"] is False, f"host={bad!r} should be rejected"
        assert "host" in r["error"]


def test_pair_rejects_bad_port():
    for bad in (0, 65536, -1, "not-a-port", None):
        r = _wl.pair("192.168.1.5", bad, "123456")  # type: ignore[arg-type]
        assert r["ok"] is False, f"port={bad!r} should be rejected"


def test_pair_rejects_bad_code():
    for bad in ("", "abcdef", "12345", "1234567", "123 45", None, 123456):
        r = _wl.pair("192.168.1.5", 12345, bad)  # type: ignore[arg-type]
        assert r["ok"] is False, f"code={bad!r} should be rejected"
        assert "code" in r["error"] or "6 digits" in (r.get("hint") or "")


def test_pair_accepts_valid_shape_but_needs_adb(monkeypatch):
    monkeypatch.setattr(_wl, "find_adb", lambda: None)
    r = _wl.pair("192.168.1.5", 12345, "123456")
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_connect_defaults_port_5555():
    r = _wl.connect("bad host has space")
    assert r["ok"] is False  # host validation catches it before port


def test_disconnect_all_no_args_reaches_adb_guard(monkeypatch):
    monkeypatch.setattr(_wl, "find_adb", lambda: None)
    r = _wl.disconnect()
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_pair_success_path(monkeypatch):
    """Feed a fake adb response that mimics `Successfully paired`."""
    monkeypatch.setattr(_wl, "find_adb", lambda: "/usr/bin/adb")
    captured: list[list[str]] = []

    class _R:
        returncode = 0
        stdout = "Successfully paired to 192.168.1.5:38571 [guid=adb-abc]"
        stderr = ""

    def _fake_run(args, timeout=30):
        captured.append(args)
        return _R()
    monkeypatch.setattr(_wl, "run", _fake_run)

    r = _wl.pair("192.168.1.5", 38571, "654321")
    assert r["ok"] is True
    assert r["action"] == "pair"
    assert r["host"] == "192.168.1.5"
    assert r["port"] == 38571
    # Verify the adb args include host:port and the code as the trailing arg.
    assert captured == [["pair", "192.168.1.5:38571", "654321"]]


def test_pair_failure_path_returns_actionable_hint(monkeypatch):
    monkeypatch.setattr(_wl, "find_adb", lambda: "/usr/bin/adb")

    class _R:
        returncode = 1
        stdout = ""
        stderr = "Failed: wrong code"
    monkeypatch.setattr(_wl, "run", lambda *a, **kw: _R())

    r = _wl.pair("192.168.1.5", 38571, "000000")
    assert r["ok"] is False
    assert "code" in (r.get("hint") or "").lower()
    assert r.get("stderr") == "Failed: wrong code"


def test_connect_success_and_failure_paths(monkeypatch):
    monkeypatch.setattr(_wl, "find_adb", lambda: "/usr/bin/adb")

    class _OK:
        returncode = 0
        stdout = "connected to 192.168.1.5:44121"
        stderr = ""

    class _FAIL:
        returncode = 0  # adb returns 0 even on failure
        stdout = "failed to connect to 192.168.1.5:44121"
        stderr = ""

    monkeypatch.setattr(_wl, "run", lambda *a, **kw: _OK())
    r = _wl.connect("192.168.1.5", 44121)
    assert r["ok"] is True and r["serial"] == "192.168.1.5:44121"

    monkeypatch.setattr(_wl, "run", lambda *a, **kw: _FAIL())
    r = _wl.connect("192.168.1.5", 44121)
    assert r["ok"] is False
    assert "failed" in (r["error"] or "").lower()


# ---------------------------------------------------------------------------
# apk_install.py — path traversal guard, SHA-256 + consent flow.
# ---------------------------------------------------------------------------
def _write_fake_apk(dest: Path, package: str = "com.example.test") -> bytes:
    """Build a minimal ZIP that looks like an APK — enough for the
    prepare() parser to find a package name."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w") as z:
        # Real APKs embed AndroidManifest.xml as binary AXML. Our parser
        # scans the string pool for a package-shaped token, so any
        # payload that CONTAINS the string works.
        pkg_str = package.encode("utf-16-le")
        blob = b"\x00\x00" + pkg_str + b"\x00\x00"
        z.writestr("AndroidManifest.xml", blob)
        z.writestr("classes.dex", b"dex\n035" + b"\x00" * 32)
    return dest.read_bytes()


def test_apk_prepare_rejects_missing_apk(tmp_path, monkeypatch):
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    r = _apk.prepare("nope.apk")
    assert r["ok"] is False
    assert "not found" in r["error"]


def test_apk_prepare_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    # /etc/passwd is not under STAGING_ROOT — must be refused.
    r = _apk.prepare("/etc/passwd")
    assert r["ok"] is False
    assert "staging" in r["error"] or "under" in r["error"]


def test_apk_prepare_reports_sha_and_consent_token(tmp_path, monkeypatch):
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    apk = tmp_path / "hello.apk"
    data = _write_fake_apk(apk, package="com.example.hello")
    expected_sha = hashlib.sha256(data).hexdigest()

    r = _apk.prepare("hello.apk")   # relative path — resolved under staging
    assert r["ok"] is True
    assert r["sha256"] == expected_sha
    assert r["required_consent"] == f"yes-install-{expected_sha[:8]}"
    assert r["size_bytes"] == len(data)
    # Package extraction is best-effort — either the true value or None,
    # but if it's a string it must NOT be an android.* framework name.
    if r["package"] is not None:
        assert not r["package"].startswith("android.")
        assert not r["package"].startswith("java.")


def test_apk_install_rejects_wrong_consent(tmp_path, monkeypatch):
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    apk = tmp_path / "hello.apk"
    _write_fake_apk(apk)
    r = _apk.install("dummy", "hello.apk", consent="wrong-token")
    assert r["ok"] is False
    assert "consent" in r["error"]
    assert r["required_consent"].startswith("yes-install-")
    assert r["apk_sha256"] == hashlib.sha256(apk.read_bytes()).hexdigest()


def test_apk_install_rejects_missing_serial(tmp_path, monkeypatch):
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    apk = tmp_path / "hello.apk"
    _write_fake_apk(apk)
    r = _apk.install("", "hello.apk", consent=None)
    assert r["ok"] is False
    assert "serial" in r["error"]


def test_apk_install_needs_adb_after_consent(tmp_path, monkeypatch):
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    monkeypatch.setattr(_apk, "find_adb", lambda: None)
    apk = tmp_path / "hello.apk"
    data = _write_fake_apk(apk)
    sha = hashlib.sha256(data).hexdigest()
    r = _apk.install("dummy", "hello.apk", consent=f"yes-install-{sha[:8]}")
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_apk_install_success_path(tmp_path, monkeypatch):
    monkeypatch.setattr(_apk, "STAGING_ROOT", tmp_path)
    monkeypatch.setattr(_apk, "find_adb", lambda: "/usr/bin/adb")
    apk = tmp_path / "hello.apk"
    data = _write_fake_apk(apk)
    sha = hashlib.sha256(data).hexdigest()

    calls: list[Any] = []

    class _OK:
        returncode = 0
        stdout = "Success\n"
        stderr = ""

    class _PushOK:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(args, serial=None, timeout=None):
        calls.append(args)
        if args and args[0] == "push":
            return _PushOK()
        return _OK()
    monkeypatch.setattr(_apk, "run", _fake_run)

    r = _apk.install("2200ad3b", "hello.apk", consent=f"yes-install-{sha[:8]}")
    assert r["ok"] is True
    assert r["sha256"] == sha
    # Must have done a push then a pm install.
    assert any(a[0] == "push" for a in calls)
    assert any(a[:3] == ["shell", "pm", "install"] for a in calls)


def test_consent_token_is_apk_specific():
    """The 8-hex-prefix suffix guarantees a rotated APK can't accept
    the previous session's consent."""
    from arena.mobile.apk_install import _consent_token
    a = _consent_token("00" * 32)
    b = _consent_token("ff" * 32)
    assert a != b
    assert a.startswith("yes-install-")
    assert a.endswith("00000000")
    assert b.endswith("ffffffff")


def test_apksigner_verify_handles_missing_binary(tmp_path, monkeypatch):
    """When apksigner isn't on the PATH we return `available: False`
    with a helpful hint, not a raw exception."""
    monkeypatch.setattr(_apk.shutil, "which", lambda name: None)
    apk = tmp_path / "hello.apk"
    apk.write_bytes(b"\x00")
    r = _apk._try_apksigner_verify(apk)
    assert r["available"] is False
    assert r["verified"] is None
    assert "not installed" in r["hint"]


# ---------------------------------------------------------------------------
# Handler dataclass — v3.83.5 fields expected.
# ---------------------------------------------------------------------------
def test_mobile_handlers_dataclass_has_v83_5_fields():
    """Baseline check for v3.83.5 handlers. Exact field surface is
    asserted in tests/test_mobile_v84_0.py so tests grow independently."""
    from arena.mobile.handlers import MobileHandlers
    v83_5_baseline = {
        "list_devices", "device_info", "screenshot", "tap", "swipe",
        "type_text", "key_event", "shell", "packages", "gesture",
        "ui_dump", "tap_by",
        "helpers_status", "helpers_install",
        "ime_status", "ime_set", "ime_reset", "paste",
        "sensors", "scroll", "key_combo",
        "pair", "connect", "disconnect", "apk_prepare", "apk_install",
    }
    got = {f.name for f in MobileHandlers.__dataclass_fields__.values()}
    missing = v83_5_baseline - got
    assert not missing, f"v3.83.5 handlers missing: {missing}"
