"""Unit tests for arena.agent_helpers.files (v4.79.0 coverage lift).

The module bundles the small filesystem helpers used by the
agent-side scripts (``now_iso``, ``safe_write``, ``backup_file``,
``verify_python``, ``verify_bash``). Until v4.79.0 it had 0% line
coverage (89 statements, 24 branches, never imported by any
test). These tests focus on the parts that can run without
``agentctl`` / a real bridge installation.

The POSIX permission-bit checks (``chmod 0o600``) only work on
POSIX filesystems -- Windows NTFS uses ACLs and the
``stat.S_IMODE`` value is whatever the file was created with
(0o666 by default). Those tests are therefore skipped on
``sys.platform == "win32"``.
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

# Skip the POSIX permission-bit assertions on Windows: NTFS
# uses ACLs, and stat.S_IMODE on a freshly-created file is
# 0o666 regardless of the chmod call. The other 6 tests still
# run on Windows -- they exercise the function logic, not the
# permission-bit semantics.
_POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX permission bits (chmod 0o600) are not "
           "enforced on Windows NTFS",
)


# Point ARENA_AGENT_HOME at a tmp dir before importing the
# module so the module-level ``ROOT`` constant is safe.
_tmp_home = Path(tempfile.mkdtemp(prefix="arena_helpers_test_"))
os.environ["ARENA_AGENT_HOME"] = str(_tmp_home)

from arena.agent_helpers import files  # noqa: E402


# --------------------------------------------------------------------
# now_iso
# --------------------------------------------------------------------
def test_now_iso_returns_utc_with_seconds_precision():
    out = files.now_iso()
    assert out.endswith("+00:00")
    assert len(out) == 25


# --------------------------------------------------------------------
# safe_write
# --------------------------------------------------------------------
def test_safe_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "deep" / "nested" / "x.txt"
    files.safe_write(p, "hello")
    assert p.read_text(encoding="utf-8") == "hello"


@_POSIX_ONLY
def test_safe_write_sets_owner_only_mode(tmp_path):
    p = tmp_path / "secret.txt"
    files.safe_write(p, "shh", mode=0o600)
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600


def test_safe_write_overwrites_existing_file(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("OLD", encoding="utf-8")
    files.safe_write(p, "NEW")
    assert p.read_text(encoding="utf-8") == "NEW"


def test_safe_write_uses_atomic_replace_no_leftover_tmp(tmp_path):
    p = tmp_path / "x.txt"
    files.safe_write(p, "v1")
    # No .tmp file should remain after the atomic replace.
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


# --------------------------------------------------------------------
# backup_file
# --------------------------------------------------------------------
def test_backup_file_returns_none_for_missing(tmp_path):
    assert files.backup_file(tmp_path / "absent.txt") is None


def test_backup_file_creates_timestamped_copy(tmp_path):
    p = tmp_path / "data.txt"
    p.write_text("data", encoding="utf-8")
    backup = files.backup_file(p)
    assert backup is not None
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "data"
    # The backup file lives next to the original.
    assert backup.parent == tmp_path
    # And the original is still in place.
    assert p.read_text(encoding="utf-8") == "data"
