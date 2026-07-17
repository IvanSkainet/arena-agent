"""v4.42.2 tests for the safe zip-extraction helper.

Covers CVE-2007-4559 / PEP 706 concerns for zip:

* absolute-path member -> rejected
* ``..`` traversal member -> rejected
* symlink member -> rejected
* zip-bomb (per-member cap) -> rejected
* zip-bomb (total-size cap) -> rejected
* NUL byte in member name -> rejected
* Windows drive-letter absolute -> rejected
* backslash-based ``..`` traversal -> rejected
* legitimate archives -> extract normally
* member reader caps size
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from arena.files.safe_extract import (
    UnsafeArchiveError,
    read_zip_member_safe,
    safe_extract_zip,
)


def _make_zip(tmp_path, members, symlink_members=None):
    """members: iterable of (name, data). symlink_members: iterable
    of (name, target) where the entry is stored as a symlink."""
    z_path = tmp_path / "arc.zip"
    with zipfile.ZipFile(z_path, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
        for name, target in (symlink_members or []):
            info = zipfile.ZipInfo(name)
            info.create_system = 3  # Unix creator
            # S_IFLNK (0o120000) in high 16 bits + world-readable
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, target)
    return z_path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_ordinary_archive_extracts(tmp_path):
    z = _make_zip(tmp_path, [
        ("hello.txt", "world"),
        ("nested/deep/file.md", "# heading"),
    ])
    dest = tmp_path / "out"
    safe_extract_zip(z, dest)
    assert (dest / "hello.txt").read_text() == "world"
    assert (dest / "nested" / "deep" / "file.md").read_text() == "# heading"


# ---------------------------------------------------------------------------
# Path traversal attacks
# ---------------------------------------------------------------------------
def test_absolute_path_member_rejected(tmp_path):
    z = _make_zip(tmp_path, [("/etc/passwd_replacement", "x")])
    dest = tmp_path / "out"
    with pytest.raises(UnsafeArchiveError, match="path-traversal"):
        safe_extract_zip(z, dest)


def test_dotdot_traversal_rejected(tmp_path):
    z = _make_zip(tmp_path, [("../../../etc/foo", "x")])
    dest = tmp_path / "out"
    with pytest.raises(UnsafeArchiveError, match="path-traversal"):
        safe_extract_zip(z, dest)


def test_dotdot_mid_path_rejected(tmp_path):
    """Sneakier form: legit-looking prefix, then dotdot."""
    z = _make_zip(tmp_path, [("plausible/../../../etc/foo", "x")])
    with pytest.raises(UnsafeArchiveError, match="path-traversal"):
        safe_extract_zip(z, tmp_path / "out")


def test_windows_drive_letter_rejected(tmp_path):
    z = _make_zip(tmp_path, [("C:/Windows/System32/foo.dll", "x")])
    with pytest.raises(UnsafeArchiveError, match="path-traversal"):
        safe_extract_zip(z, tmp_path / "out")


def test_backslash_dotdot_rejected(tmp_path):
    """Windows-style separator normalisation must still trip
    the check -- zip stores forward slashes but a hostile tool
    could write backslashes."""
    z = _make_zip(tmp_path, [("evil\\..\\..\\etc\\foo", "x")])
    with pytest.raises(UnsafeArchiveError, match="path-traversal"):
        safe_extract_zip(z, tmp_path / "out")


def test_nul_byte_in_name_rejected():
    """zipfile's own writer truncates at NUL when writing, so
    we can't build a real archive with a NUL member name. But
    the helper's traversal check is what protects downstream
    code -- test it against the string directly."""
    from arena.files.safe_extract import _member_is_traversal
    assert _member_is_traversal("normal\x00hidden") is True
    assert _member_is_traversal("evil\x00.txt") is True


# ---------------------------------------------------------------------------
# Symlink members
# ---------------------------------------------------------------------------
def test_symlink_member_rejected(tmp_path):
    z = _make_zip(tmp_path, [("ok.txt", "hello")],
                  symlink_members=[("link", "/etc/passwd")])
    with pytest.raises(UnsafeArchiveError, match="symlink"):
        safe_extract_zip(z, tmp_path / "out")


# ---------------------------------------------------------------------------
# Zip bombs
# ---------------------------------------------------------------------------
def test_per_member_size_cap(tmp_path):
    z = _make_zip(tmp_path, [("big", "x" * 200)])
    with pytest.raises(UnsafeArchiveError, match="per-member"):
        safe_extract_zip(z, tmp_path / "out", max_member_bytes=100)


def test_total_size_cap(tmp_path):
    z = _make_zip(tmp_path, [
        ("a", "x" * 80),
        ("b", "y" * 80),
        ("c", "z" * 80),
    ])
    with pytest.raises(UnsafeArchiveError,
                       match="exceeding cap"):
        safe_extract_zip(z, tmp_path / "out",
                         max_uncompressed_bytes=200,
                         max_member_bytes=100)


# ---------------------------------------------------------------------------
# Belt+suspenders: rejection happens before any bytes are written
# ---------------------------------------------------------------------------
def test_rejection_is_atomic_no_partial_write(tmp_path):
    """If the second member is malicious, we must not have
    written the first member either. Two-pass design guarantees
    this: rejection during the pre-scan means nothing writes."""
    z = _make_zip(tmp_path, [
        ("innocent.txt", "hello"),
        ("../../../evil", "boom"),
    ])
    dest = tmp_path / "out"
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(z, dest)
    # Nothing should have been created inside dest (the mkdir
    # itself is fine, we just care no member bytes leaked).
    if dest.exists():
        assert list(dest.iterdir()) == []


# ---------------------------------------------------------------------------
# read_zip_member_safe
# ---------------------------------------------------------------------------
def test_read_member_ordinary(tmp_path):
    z = _make_zip(tmp_path, [("file.txt", "content")])
    with zipfile.ZipFile(z) as zf:
        assert read_zip_member_safe(zf, "file.txt") == b"content"


def test_read_member_size_cap(tmp_path):
    z = _make_zip(tmp_path, [("file.txt", "x" * 500)])
    with zipfile.ZipFile(z) as zf:
        with pytest.raises(UnsafeArchiveError,
                           match="exceeding read cap"):
            read_zip_member_safe(zf, "file.txt", max_bytes=100)


def test_read_member_nul_in_name_rejected(tmp_path):
    z = _make_zip(tmp_path, [("file.txt", "x")])
    with zipfile.ZipFile(z) as zf:
        with pytest.raises(UnsafeArchiveError, match="NUL"):
            read_zip_member_safe(zf, "file\x00.txt")
