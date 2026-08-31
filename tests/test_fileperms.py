"""A chmod that fails must not look like a chmod that worked.

Eight call sites tightened sensitive files -- the audit log, the memory
database, rotated logs -- with ``os.chmod(path, 0o600)`` wrapped in
``except Exception: pass``. When that chmod failed the file stayed
world-readable and nothing said so. bandit flags the shape (B110); these
tests pin the behaviour that replaced it.
"""
from __future__ import annotations

import logging
import os
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.fileperms import restrict  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="POSIX mode bits are not meaningful on Windows"
)


def _make(tmp_path: Path, mode: int) -> Path:
    target = tmp_path / "data"
    target.write_text("secret", encoding="utf-8")
    target.chmod(mode)
    return target


def test_it_actually_restricts(tmp_path):
    target = _make(tmp_path, 0o644)
    assert restrict(target, 0o600) is True
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_failure_on_an_exposed_file_warns(tmp_path, caplog):
    """The case that matters: chmod failed and the file is readable by others."""
    target = _make(tmp_path, 0o644)
    with caplog.at_level(logging.WARNING), \
            mock.patch("os.chmod", side_effect=PermissionError("denied")):
        assert restrict(target, 0o600, what="the audit log") is False
    assert "the audit log" in caplog.text
    assert "readable by other users" in caplog.text


def test_failure_on_an_already_tight_file_is_quiet(tmp_path, caplog):
    """No warning when nothing is exposed -- otherwise the real one drowns."""
    target = _make(tmp_path, 0o600)
    with caplog.at_level(logging.WARNING), \
            mock.patch("os.chmod", side_effect=PermissionError("denied")):
        assert restrict(target, 0o600) is False
    assert caplog.text == ""


def test_filesystem_without_modes_is_quiet(tmp_path, caplog):
    """FAT/exFAT/network mounts raise and there is nothing to act on."""
    target = _make(tmp_path, 0o644)
    with caplog.at_level(logging.WARNING), \
            mock.patch("os.chmod", side_effect=NotImplementedError()):
        assert restrict(target, 0o600) is False
    assert caplog.text == ""


def test_a_vanished_file_does_not_raise(tmp_path, caplog):
    """Best-effort means best-effort: never take down the caller."""
    with caplog.at_level(logging.WARNING):
        assert restrict(tmp_path / "gone", 0o600) is False
    assert caplog.text == ""


def test_group_or_world_modes_are_not_reported_as_exposure(tmp_path, caplog):
    """Asking for 0o644 and failing is not a confidentiality problem."""
    target = _make(tmp_path, 0o644)
    with caplog.at_level(logging.WARNING), \
            mock.patch("os.chmod", side_effect=PermissionError("denied")):
        assert restrict(target, 0o644) is False
    assert caplog.text == ""


def test_audit_log_write_still_tightens_the_file(tmp_path):
    """End to end through the real caller, not just the helper."""
    from arena.observability import audit

    log = tmp_path / "audit.jsonl"
    log.write_text("", encoding="utf-8")
    log.chmod(0o644)
    audit.write_audit_event(
        {"type": "probe"}, audit_path=log, app_dir=tmp_path,
        lock=audit.audit_lock, utc_now_fn=lambda: "now",
    )
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
