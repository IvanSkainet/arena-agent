"""Safe zip / tar extraction helpers (v4.42.2, security
hardening).

The stdlib ``zipfile.ZipFile.extractall()`` and
``tarfile.TarFile.extractall()`` are vulnerable to two classes
of directory-escape attack, both catalogued as
CVE-2007-4559 / PEP 706:

* **Absolute paths in archive members.** An entry named
  ``/etc/cron.d/backdoor`` overwrites (or creates) a file at
  the absolute path on the extracting host, regardless of the
  supplied destination directory. Python's stdlib strips the
  leading slash on POSIX but preserves it on Windows.
* **``..`` traversal in archive members.** An entry named
  ``../../../etc/passwd`` navigates out of the destination
  and writes wherever the process user can reach.

Additional risks specific to zip:

* **Symlink members** (present in zip via extra field 0x756E,
  and universally in tar). A member declared as a symlink
  pointing to ``/etc/`` followed by a second member that
  writes into it lets an archive plant into an arbitrary
  location.
* **Zip-bomb size ratios.** A 1 MB zip that expands to 40 GB.
  We enforce a cap so a hostile archive cannot fill the disk.

This module is used by every code path in arena/ that
extracts a zip whose contents came from off-host (auto-update
release download, skills marketplace install, APK helper).
The apk_install case is slightly different -- the APK zip is
inspected but its member payloads are not written to the host
filesystem -- so it uses the ``read_zip_member_safe`` helper
instead of ``safe_extract_zip``.

Python 3.12 added ``TarFile.extraction_filter`` (PEP 706).
We are not on 3.12 as a floor and we still support the zip
case which PEP 706 does not touch, so this module is the
project-wide answer.

Public API::

    safe_extract_zip(zip_path, dest_dir, *, max_uncompressed_bytes=...)
    read_zip_member_safe(zf, member_name, *, max_bytes=...)
"""
from __future__ import annotations

import zipfile
from pathlib import Path


# 4 GiB total uncompressed cap. Empirically the arena release
# zip is ~3 MB, skill zips are typically <1 MB. A legitimate
# archive that trips this cap probably isn't one we want to
# install anyway (either wrong file or a compression bomb).
DEFAULT_MAX_UNCOMPRESSED = 4 * 1024 * 1024 * 1024

# Per-member cap, defence-in-depth for the case of a single
# gigantic member inside an otherwise normal-looking archive.
# 1 GiB is plenty for anything reasonable.
DEFAULT_MAX_MEMBER = 1024 * 1024 * 1024


class UnsafeArchiveError(ValueError):
    """Raised when an archive is rejected as unsafe.

    Subclass of ``ValueError`` so callers that already catch
    ``ValueError`` around extraction don't need to be updated.
    The message names the offending member so a legitimate
    archive that trips a check by accident is easy to diagnose.
    """


def _member_is_traversal(name: str) -> bool:
    """Return True when a zip member name would escape the
    destination directory.

    Checks catch:
      * absolute paths (``/etc/passwd``, ``C:\\Windows\\foo``);
      * ``..`` anywhere in the parts tuple, including hidden
        ones like ``a/../b`` that PurePath doesn't normalise
        until ``resolve()``;
      * empty strings and lone slashes;
      * NUL bytes (some tools splice them in to confuse path
        parsers -- reject on principle).
    """
    if not name or name in (".", "/"):
        return True
    if "\x00" in name:
        return True
    # Zip stores forward slashes even on Windows. Normalise so
    # a single check catches ``a\..\..\b`` too.
    normalised = name.replace("\\", "/")
    if normalised.startswith("/"):
        return True
    # Windows drive-letter absolutes.
    if len(normalised) >= 2 and normalised[1] == ":":
        return True
    parts = normalised.split("/")
    if ".." in parts:
        return True
    return False


def _member_is_symlink(info: zipfile.ZipInfo) -> bool:
    """Return True when the zip member represents a symlink.

    Zip encodes symlinks in the high 16 bits of ``external_attr``
    using the classic Unix stat mode. Symlink members are
    silently converted to real files during extraction otherwise,
    which is exactly the risk PEP 706 flags for tarfile.
    """
    # High 16 bits store the Unix mode when the "made by" byte
    # indicates a Unix creator. Anything looking like a symlink
    # (S_IFLNK = 0o120000) is rejected.
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def safe_extract_zip(
    zip_path: Path | str,
    dest_dir: Path | str,
    *,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED,
    max_member_bytes: int = DEFAULT_MAX_MEMBER,
) -> None:
    """Extract a zip file safely, rejecting archives that would
    escape ``dest_dir`` or exceed the zip-bomb caps.

    Raises ``UnsafeArchiveError`` on rejection. On success, all
    members have been written under ``dest_dir``.

    Compared with ``ZipFile.extractall`` this helper:

    * inspects every member name (``_member_is_traversal``);
    * refuses symlink members outright;
    * post-validates by ``resolve()``-relative-to-dest, so an
      escape via a member name that PurePath normalises
      differently than the OS is still caught;
    * caps total uncompressed size + per-member size to
      neutralise zip bombs.

    Contract for callers: ``dest_dir`` should be a fresh
    per-extraction directory that the caller is prepared to
    delete on failure. This helper does NOT roll back partial
    writes.
    """
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        # First pass: reject the whole archive before writing
        # any byte. This is the "belt" of belt+suspenders --
        # even a partial extraction of a hostile archive is
        # bad because side effects (mkdir of arbitrary paths)
        # can happen before the traversal check would have
        # fired mid-loop.
        total_size = 0
        for info in zf.infolist():
            if _member_is_traversal(info.filename):
                raise UnsafeArchiveError(
                    f"archive contains path-traversal member: "
                    f"{info.filename!r}"
                )
            if _member_is_symlink(info):
                raise UnsafeArchiveError(
                    f"archive contains a symlink member: "
                    f"{info.filename!r}"
                )
            if info.file_size > max_member_bytes:
                raise UnsafeArchiveError(
                    f"archive member {info.filename!r} declares "
                    f"{info.file_size} bytes, exceeding per-member "
                    f"cap of {max_member_bytes}"
                )
            total_size += info.file_size
            if total_size > max_uncompressed_bytes:
                raise UnsafeArchiveError(
                    f"archive declares {total_size} uncompressed "
                    f"bytes, exceeding cap of {max_uncompressed_bytes}"
                )
        # Second pass: actually extract, with a post-check on
        # each resolved destination path. Two layers because
        # a member name can pass the string check but still
        # resolve outside dest on a case-insensitive filesystem
        # (Windows / macOS default HFS+) or via a locale-
        # dependent unicode normalisation quirk. resolve() is
        # the ground truth.
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            try:
                target.relative_to(dest)
            except ValueError:
                raise UnsafeArchiveError(
                    f"archive member {info.filename!r} resolves "
                    f"outside destination {dest}"
                )
            zf.extract(info, dest)


def read_zip_member_safe(
    zf: zipfile.ZipFile,
    member_name: str,
    *,
    max_bytes: int = DEFAULT_MAX_MEMBER,
) -> bytes:
    """Read a single zip member into memory with a size cap.

    For callers that need to *inspect* a zip entry (e.g. APK's
    ``AndroidManifest.xml``) without writing it to disk. Returns
    the raw bytes. Raises ``UnsafeArchiveError`` when the
    member's declared size exceeds ``max_bytes``, so a
    hostile archive cannot exhaust memory.

    Does not do a path-traversal check because the caller
    already knows the exact name they asked for. Does still
    reject NUL bytes in the requested name as a sanity check.
    """
    if "\x00" in member_name:
        raise UnsafeArchiveError(
            f"member name contains NUL byte: {member_name!r}"
        )
    info = zf.getinfo(member_name)
    if info.file_size > max_bytes:
        raise UnsafeArchiveError(
            f"member {member_name!r} declares {info.file_size} "
            f"bytes, exceeding read cap of {max_bytes}"
        )
    with zf.open(info) as fh:
        # read(max_bytes + 1) so we can detect a lying header
        # (declared size < actual). Real archives always
        # declare correctly.
        data = fh.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise UnsafeArchiveError(
                f"member {member_name!r} produced more bytes than "
                f"its declared size after decompression"
            )
        return data
