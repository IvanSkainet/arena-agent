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

import inspect
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

import arena.files.safe_extract as safe_extract_module
from arena.files.safe_extract import (
    TarLimits,
    UnsafeArchiveError,
    read_zip_member_safe,
    safe_extract_tar,
    safe_extract_zip,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


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


# ---------------------------------------------------------------------------
# tar (#242)
#
# The module docstring called itself "the project-wide answer" to
# CVE-2007-4559 from v4.42.2, but only implemented the zip half. So
# scripts/core/time_machine.py used a bare tar.extractall() and could be
# made to write outside its destination. These mirror the zip cases, plus
# the member kinds tar has and zip does not.
# ---------------------------------------------------------------------------


def _make_tar(path, members, *, mode="w:gz"):
    """Build a tar whose member names are supplied verbatim."""
    with tarfile.open(path, mode) as tf:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            data = payload.encode()
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def test_tar_ordinary_archive_extracts(tmp_path):
    src = _make_tar(tmp_path / "a.tar.gz", [("dir/file.txt", "hello")])
    dest = tmp_path / "out"
    safe_extract_tar(src, dest)
    assert (dest / "dir" / "file.txt").read_text() == "hello"


def test_tar_dotdot_traversal_rejected(tmp_path):
    """The exact shape demonstrated on #242."""
    src = _make_tar(tmp_path / "evil.tar.gz", [("../../escaped.txt", "pwned")])
    with pytest.raises(UnsafeArchiveError, match="path-traversal"):
        safe_extract_tar(src, tmp_path / "out")
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_tar_absolute_path_member_rejected(tmp_path):
    src = _make_tar(tmp_path / "abs.tar.gz", [("/etc/cron.d/backdoor", "x")])
    with pytest.raises(UnsafeArchiveError, match="path-traversal"):
        safe_extract_tar(src, tmp_path / "out")


def test_tar_dotdot_mid_path_rejected(tmp_path):
    src = _make_tar(tmp_path / "mid.tar.gz", [("a/../../b.txt", "x")])
    with pytest.raises(UnsafeArchiveError, match="path-traversal"):
        safe_extract_tar(src, tmp_path / "out")


def test_tar_symlink_member_rejected(tmp_path):
    """Tar stores symlinks natively; a link to /etc plants anywhere."""
    src = tmp_path / "sym.tar.gz"
    with tarfile.open(src, "w:gz") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc"
        tf.addfile(info)
    with pytest.raises(UnsafeArchiveError, match="link member"):
        safe_extract_tar(src, tmp_path / "out")


def test_tar_hardlink_member_rejected(tmp_path):
    """A hardlink can alias a file outside the destination."""
    src = tmp_path / "hard.tar.gz"
    with tarfile.open(src, "w:gz") as tf:
        info = tarfile.TarInfo("alias")
        info.type = tarfile.LNKTYPE
        info.linkname = "../../outside"
        tf.addfile(info)
    with pytest.raises(UnsafeArchiveError, match="link member"):
        safe_extract_tar(src, tmp_path / "out")


def test_tar_device_member_rejected(tmp_path):
    """Creating device nodes is never legitimate for our archives."""
    src = tmp_path / "dev.tar.gz"
    with tarfile.open(src, "w:gz") as tf:
        info = tarfile.TarInfo("null")
        info.type = tarfile.CHRTYPE
        info.devmajor, info.devminor = 1, 3
        tf.addfile(info)
    with pytest.raises(UnsafeArchiveError, match="device/FIFO"):
        safe_extract_tar(src, tmp_path / "out")


def test_tar_per_member_size_cap(tmp_path):
    src = _make_tar(tmp_path / "big.tar.gz", [("f", "x" * 4096)])
    with pytest.raises(UnsafeArchiveError, match="per-member cap"):
        safe_extract_tar(src, tmp_path / "out", limits=TarLimits(max_member_bytes=100))


def test_tar_total_size_cap(tmp_path):
    src = _make_tar(tmp_path / "many.tar.gz",
                    [(f"f{i}", "x" * 500) for i in range(10)])
    with pytest.raises(UnsafeArchiveError, match="exceeding cap"):
        safe_extract_tar(src, tmp_path / "out", limits=TarLimits(max_uncompressed_bytes=1000))


def test_tar_rejection_is_atomic_no_partial_write(tmp_path):
    """A hostile member must not be preceded by real writes.

    The traversal entry is last, so a single-pass implementation would
    already have created `good.txt` before noticing. Rejecting the whole
    archive up front is the property under test.
    """
    src = _make_tar(tmp_path / "mixed.tar.gz",
                    [("good.txt", "ok"), ("../escaped.txt", "pwned")])
    dest = tmp_path / "out"
    with pytest.raises(UnsafeArchiveError):
        safe_extract_tar(src, dest)
    assert not (dest / "good.txt").exists(), (
        "a member was written before the archive was rejected"
    )


def test_tar_member_count_cap(tmp_path):
    """Byte caps alone do not bound a tar (found in review on #243).

    `getmembers()` materialises every member before any size check can
    run, so an archive of zero-byte entries costs memory proportional to
    its member count while passing every byte limit. Measured before the
    fix: 400k members, 2.4 MB on disk, ~170 MB RSS, and extraction was
    ALLOWED against a 1000-byte cap.
    """
    src = _make_tar(tmp_path / "many.tar.gz",
                    [(f"f{i}", "") for i in range(50)])
    with pytest.raises(UnsafeArchiveError, match="more than 10 members"):
        safe_extract_tar(src, tmp_path / "out", limits=TarLimits(max_members=10))


def test_tar_member_cap_fires_before_exhausting_the_archive(tmp_path):
    """The cap must stop enumeration, not just report afterwards.

    A check that runs after the whole member list is built prevents the
    extraction but not the memory cost, which is the actual attack.
    """
    src = _make_tar(tmp_path / "lots.tar.gz",
                    [(f"f{i}", "") for i in range(200)])
    with tarfile.open(src) as tf:
        seen = []
        original = tf.__class__.next

        def counting_next(self):
            member = original(self)
            if member is not None:
                seen.append(member.name)
            return member

        tf.__class__.next = counting_next
        try:
            with pytest.raises(UnsafeArchiveError):
                safe_extract_tar(src, tmp_path / "out", limits=TarLimits(max_members=5))
        finally:
            tf.__class__.next = original
    assert len(seen) < 200, (
        f"enumerated {len(seen)} members despite a cap of 5; the cap "
        f"is not stopping the scan"
    )


def test_tar_resolve_check_is_load_bearing_on_the_supported_floor(
        tmp_path, monkeypatch):
    """resolve() is the only guard on 3.10/3.11, so test it there.

    Sabotage kept passing with the check disabled, and the honest reason
    is that on 3.12+ ``filter="data"`` catches this case first. That
    makes resolve() redundant on a modern interpreter -- but not on the
    floor this project declares (``requires-python = ">=3.10"``), where
    the filter argument does not exist.

    So the coverage has to name the condition. Emulating the floor by
    dropping the PEP 706 kwargs, and measured both ways:

        floor + resolve()      -> refused
        floor, resolve removed -> ESCAPED

    Without this, the check has no test that fails when it is deleted,
    and the next person to tidy it up would be removing the only
    protection four of the five supported interpreters have.
    """
    # Emulate the 3.10/3.11 floor: extract without PEP 706 filtering, so
    # resolve() is the only guard left standing.
    def _unfiltered(tf, member, dest):
        tf.extract(member, dest)

    monkeypatch.setattr(safe_extract_module, "_extract_one", _unfiltered)

    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    try:
        (dest / "sub").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover
        pytest.skip("symlink creation not permitted here")

    src = _make_tar(tmp_path / "innocent.tar.gz", [("sub/file.txt", "pwned")])
    with pytest.raises(UnsafeArchiveError, match="resolves outside"):
        safe_extract_tar(src, dest)
    assert not (outside / "file.txt").exists(), (
        "a member escaped through a pre-existing symlink in the destination"
    )


def test_pep706_filter_is_requested_where_available():
    """Defence in depth must actually be in place on 3.12+.

    Reads the source rather than the call, because the filter is passed
    through a getattr() indirection that exists to satisfy two analysers
    (see _extract_one). An assertion on behaviour would not distinguish
    "filtered" from "our checks happened to catch it first".
    """
    import sys as _sys

    source = inspect.getsource(safe_extract_module._extract_one)
    assert 'filter="data"' in source, (
        "PEP 706 filtering is no longer requested"
    )
    assert "sys.version_info >= (3, 12)" in source, (
        "the version guard is gone; filter= does not exist on the 3.10 floor"
    )
    if _sys.version_info >= (3, 12):
        assert "extract(member, dest, filter=" in source


def test_time_machine_uses_the_safe_helper():
    """The caller that motivated this must not regress to extractall().

    A helper nobody calls fixes nothing, and `tar.extractall(` is the
    form that reads naturally.
    """
    source = (REPO_ROOT / "scripts" / "core" / "time_machine.py").read_text(
        encoding="utf-8")
    assert "safe_extract_tar(" in source, (
        "time_machine.py no longer uses safe_extract_tar"
    )
    # Ignore comment lines: the file explains the old call by name, and a
    # naive substring search flags that prose. (Same self-match trap as
    # the AGENTS.md task gate -- a detector must not match its own
    # explanation.)
    code = [ln for ln in source.splitlines() if not ln.lstrip().startswith("#")]
    offenders = [ln.strip() for ln in code if "extractall(" in ln]
    assert not offenders, (
        f"time_machine.py reintroduced a bare extractall(): {offenders}"
    )
