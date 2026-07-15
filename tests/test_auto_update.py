"""Tests for v3.85.0: auto-update.

Covers pure-Python surface without hitting GitHub / the filesystem
outside a tempdir:

  * parse_version / is_newer semantics
  * _pick_asset prefers versioned zip over the arena-agent.zip alias
  * check_updates surfaces HTTP errors gracefully (monkeypatched fetch)
  * download_release verifies sha256 mismatch
  * consent_token round-trips
  * _swap_unix moves each REPLACE target and skips missing ones
  * apply_update refuses without consent and returns the expected token
  * AdminHandlers dataclass grows 4 new fields
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------
def test_parse_version_strips_leading_v_and_ignores_rc_suffix():
    from arena.admin.auto_update import parse_version
    assert parse_version("v3.84.7") == (3, 84, 7)
    assert parse_version("3.84.7") == (3, 84, 7)
    assert parse_version("v3.85.0-rc1") == (3, 85, 0)
    assert parse_version("") == (0,)
    assert parse_version("garbage") == (0,)


def test_is_newer_semver_lite_ordering():
    from arena.admin.auto_update import is_newer
    assert is_newer("v3.85.0", "v3.84.7") is True
    assert is_newer("v3.84.7", "3.84.7") is False
    assert is_newer("v3.84.8", "v3.84.7") is True
    assert is_newer("v3.84.7", "v3.85.0") is False


# ---------------------------------------------------------------------------
# Asset picking
# ---------------------------------------------------------------------------
def test_pick_asset_prefers_versioned_zip_over_alias():
    from arena.admin.auto_update import _pick_asset
    assets = [
        {"name": "arena-agent.zip"},
        {"name": "arena-agent-v3.85.0.zip"},
        {"name": "README.md"},
    ]
    a = _pick_asset(assets)
    assert a is not None and a["name"] == "arena-agent-v3.85.0.zip"


def test_pick_asset_falls_back_to_alias_when_versioned_missing():
    from arena.admin.auto_update import _pick_asset
    a = _pick_asset([{"name": "arena-agent.zip"}, {"name": "notes.txt"}])
    assert a["name"] == "arena-agent.zip"


def test_pick_asset_returns_none_for_no_zips():
    from arena.admin.auto_update import _pick_asset
    assert _pick_asset([{"name": "notes.txt"}]) is None
    assert _pick_asset([]) is None


# ---------------------------------------------------------------------------
# check_updates
# ---------------------------------------------------------------------------
def test_check_updates_surfaces_http_error_gracefully(monkeypatch):
    import urllib.error
    from arena.admin import auto_update as au

    def _boom(url):
        raise urllib.error.HTTPError(url, 403, "Rate limited", {}, None)

    monkeypatch.setattr(au, "_http_get_json", _boom)
    r = au.check_updates(current_version="v3.84.7")
    assert r["ok"] is False
    assert "403" in r["error"]


def test_check_updates_reports_needs_update(monkeypatch):
    from arena.admin import auto_update as au

    def _fake_fetch(url):
        return {
            "tag_name": "v3.85.0",
            "html_url": "https://example/release",
            "published_at": "2026-07-15T12:00:00Z",
            "body": "release notes here",
            "assets": [{
                "name": "arena-agent-v3.85.0.zip",
                "browser_download_url": "https://example/arena-agent-v3.85.0.zip",
                "size": 5_000_000,
                "digest": "sha256:abcd",
            }],
        }

    monkeypatch.setattr(au, "_http_get_json", _fake_fetch)
    r = au.check_updates(current_version="v3.84.7")
    assert r["ok"] is True
    assert r["latest"] == "3.85.0"
    assert r["needs_update"] is True
    assert r["asset_name"] == "arena-agent-v3.85.0.zip"
    assert r["asset_digest"] == "sha256:abcd"


def test_check_updates_reports_no_update_when_current_matches(monkeypatch):
    from arena.admin import auto_update as au

    def _fake_fetch(url):
        return {"tag_name": "v3.84.7",
                "assets": [{"name": "arena-agent.zip",
                            "browser_download_url": "u",
                            "size": 1, "digest": "sha256:00"}]}

    monkeypatch.setattr(au, "_http_get_json", _fake_fetch)
    r = au.check_updates(current_version="v3.84.7")
    assert r["ok"] is True
    assert r["needs_update"] is False


# ---------------------------------------------------------------------------
# Download + verify
# ---------------------------------------------------------------------------
def test_download_release_detects_sha_mismatch(monkeypatch, tmp_path):
    from arena.admin import auto_update as au

    payload = b"fake-zip-contents"
    real_sha = hashlib.sha256(payload).hexdigest()

    class _FakeResp:
        def __init__(self, data): self._data = data
        def read(self, n=-1):
            d = self._data; self._data = b""
            return d
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def _fake_urlopen(req, timeout=None):
        return _FakeResp(payload)

    monkeypatch.setattr(au.urllib.request, "urlopen", _fake_urlopen)

    # First: wrong expected sha -> mismatch.
    r = au.download_release(
        asset_url="https://example/x.zip",
        asset_name="x.zip",
        expected_sha256="sha256:" + "0" * 64,
        dest_dir=str(tmp_path / "bad"),
    )
    assert r["ok"] is False
    assert "mismatch" in r["error"]

    # Right sha -> success.
    r = au.download_release(
        asset_url="https://example/x.zip",
        asset_name="x.zip",
        expected_sha256="sha256:" + real_sha,
        dest_dir=str(tmp_path / "good"),
    )
    assert r["ok"] is True
    assert r["sha256"] == real_sha
    assert Path(r["path"]).exists()


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------
def test_consent_token_shape_and_stability():
    from arena.admin.auto_update import consent_token
    t = consent_token(tag="v3.85.0", sha256="abcd")
    assert t.startswith("yes-update-")
    assert len(t) == len("yes-update-") + 8
    # Deterministic.
    assert consent_token(tag="v3.85.0", sha256="abcd") == t
    # Different inputs -> different tokens.
    assert consent_token(tag="v3.85.1", sha256="abcd") != t


# ---------------------------------------------------------------------------
# _swap_unix
# ---------------------------------------------------------------------------
def test_swap_unix_moves_replace_targets_and_ignores_missing(tmp_path,
                                                             monkeypatch):
    from arena.admin import auto_update as au
    install = tmp_path / "install"
    payload = tmp_path / "payload"
    (install / "arena").mkdir(parents=True)
    (install / "arena" / "old.txt").write_text("old")
    (install / "keep.log").write_text("must not be touched")
    (payload / "arena").mkdir(parents=True)
    (payload / "arena" / "new.txt").write_text("new")
    (payload / "unified_bridge.py").write_text("print('new')")
    # `docs/` deliberately absent from payload -- must not blow up.

    r = au._swap_unix(payload, install)
    assert r["ok"] is True
    assert "arena" in r["swapped"]
    assert "unified_bridge.py" in r["swapped"]
    assert "docs" not in r["swapped"]
    # Old file gone, new file in place.
    assert not (install / "arena" / "old.txt").exists()
    assert (install / "arena" / "new.txt").read_text() == "new"
    assert (install / "unified_bridge.py").read_text() == "print('new')"
    # Untouched.
    assert (install / "keep.log").read_text() == "must not be touched"


# ---------------------------------------------------------------------------
# apply_update consent gate
# ---------------------------------------------------------------------------
def test_apply_update_refuses_without_consent(monkeypatch):
    from arena.admin import auto_update as au
    r = au.apply_update(
        asset_url="https://example/x.zip",
        asset_name="arena-agent-v3.85.0.zip",
        tag="v3.85.0",
        expected_sha256="sha256:" + "a" * 64,
        consent="",
    )
    assert r["ok"] is False
    assert "consent" in r["error"]


def test_apply_update_refuses_wrong_consent(monkeypatch):
    from arena.admin import auto_update as au
    r = au.apply_update(
        asset_url="u", asset_name="x.zip", tag="v3.85.0",
        expected_sha256="sha256:aa", consent="yes-update-deadbeef",
    )
    assert r["ok"] is False


def test_apply_update_end_to_end_on_posix_writes_new_files(monkeypatch,
                                                            tmp_path):
    """Simulate the whole apply path on a fake install root."""
    from arena.admin import auto_update as au
    if au._WIN:
        pytest.skip("Windows path exercised in a separate integration test")

    install = tmp_path / "install"
    (install / "arena").mkdir(parents=True)
    (install / "arena" / "old.py").write_text("# old")
    monkeypatch.setattr(au, "_install_root", lambda: install)

    # Build a small zip payload wrapping in arena-agent/ like release zips do.
    payload_zip = tmp_path / "payload.zip"
    with zipfile.ZipFile(payload_zip, "w") as zf:
        zf.writestr("arena-agent/arena/new.py", "# new")
        zf.writestr("arena-agent/unified_bridge.py", "print('new')")

    def _fake_download(*, asset_url, asset_name, expected_sha256=None,
                       dest_dir=None):
        staging = tmp_path / "staging"
        staging.mkdir(exist_ok=True)
        dst = staging / asset_name
        import shutil
        shutil.copy(payload_zip, dst)
        return {"ok": True, "path": str(dst),
                "sha256": expected_sha256.split(":", 1)[-1],
                "size_bytes": dst.stat().st_size,
                "staging_dir": str(staging)}

    monkeypatch.setattr(au, "download_release", _fake_download)

    tag = "v3.85.0"
    sha = "a" * 64
    consent = au.consent_token(tag=tag, sha256=sha)
    r = au.apply_update(
        asset_url="https://example/x.zip",
        asset_name="arena-agent-v3.85.0.zip",
        tag=tag, expected_sha256=f"sha256:{sha}",
        consent=consent, restart=False,
    )
    assert r["ok"] is True, r
    assert r["applied_version"] == "3.85.0"
    assert (install / "arena" / "new.py").read_text() == "# new"
    assert (install / "unified_bridge.py").read_text() == "print('new')"
    # Old file was replaced with the new tree.
    assert not (install / "arena" / "old.py").exists()


# ---------------------------------------------------------------------------
# AdminHandlers dataclass surface
# ---------------------------------------------------------------------------
def test_admin_handlers_dataclass_carries_update_fields():
    from arena.admin.handlers import AdminHandlers
    fields = {f.name for f in AdminHandlers.__dataclass_fields__.values()}
    for name in ("update_status", "update_check",
                 "update_apply", "update_restart"):
        assert name in fields, f"missing v3.85.0 handler {name}"
