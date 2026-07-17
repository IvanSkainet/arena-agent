"""v4.42.0 tests that APK staging lives under ~/.arena/ with
mode 0o700 instead of the pre-v4.42.0 world-writable
/tmp/arena-apk-staging (audit hardening #4).
"""
from __future__ import annotations

import importlib
import os
import stat
from pathlib import Path

import pytest


@pytest.fixture
def apk_module(monkeypatch, tmp_path):
    """Reload arena.mobile.apk_install with HOME pointing at a
    fresh tmp dir so tests don't touch a real user's ~/.arena."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ARENA_APK_STAGING", raising=False)
    import arena.mobile.apk_install as m
    importlib.reload(m)
    return m


def test_staging_root_defaults_to_arena_home(apk_module, tmp_path):
    """No env override -> under ~/.arena/apk-staging (not /tmp)."""
    assert apk_module.STAGING_ROOT == tmp_path / ".arena" / "apk-staging"


def test_staging_root_not_hardcoded_shared_path(apk_module):
    """Regression: the pre-v4.42.0 default was ``/tmp/arena-apk-staging``
    which lets a co-tenant pre-plant a symlink at that name and
    redirect uploaded APKs to any path the bridge user could write.
    The new default derives from HOME, so the exact-string match on
    the old value is the tightest guard we can write without
    reintroducing platform-specific path logic in the test."""
    assert str(apk_module.STAGING_ROOT) != "/tmp/arena-apk-staging"
    # And the path must be under $HOME (or the env override,
    # which the sibling test covers), never a bare /tmp entry.
    assert ".arena" in str(apk_module.STAGING_ROOT), (
        f"unexpected staging root: {apk_module.STAGING_ROOT}"
    )


def test_env_override_wins(monkeypatch, tmp_path):
    """Operators with large-file staging on another volume can
    point ARENA_APK_STAGING at it. Env wins over default."""
    override = tmp_path / "big-volume" / "apk"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ARENA_APK_STAGING", str(override))
    import arena.mobile.apk_install as m
    importlib.reload(m)
    assert m.STAGING_ROOT == override


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_ensure_staging_root_creates_mode_700(apk_module):
    """First call must create the directory AND set 0o700 so a
    co-tenant on the same box cannot list uploaded APK metadata."""
    apk_module._ensure_staging_root()
    assert apk_module.STAGING_ROOT.exists()
    mode = stat.S_IMODE(os.stat(apk_module.STAGING_ROOT).st_mode)
    assert mode == 0o700, f"expected 0o700, got {oct(mode)}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_ensure_staging_root_tightens_parent(apk_module):
    """The ~/.arena parent should also end up 0o700 -- otherwise
    the child directory mode is moot because the parent listing
    is world-readable."""
    apk_module._ensure_staging_root()
    parent_mode = stat.S_IMODE(os.stat(apk_module.STAGING_ROOT.parent).st_mode)
    assert parent_mode == 0o700, f"expected 0o700, got {oct(parent_mode)}"


def test_ensure_staging_root_is_idempotent(apk_module):
    """Calling twice must not raise. Real code paths call it
    lazily on every persist_uploaded_apk / ensure_apk_ready."""
    apk_module._ensure_staging_root()
    apk_module._ensure_staging_root()  # would raise if not idempotent
