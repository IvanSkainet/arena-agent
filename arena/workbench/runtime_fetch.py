"""Download integrity + archive containment for managed runtimes.

Split out of `runtimes.py` in v4.163.0: that module crossed the 600-line
runtime cap while bug #51 was being fixed, and this is the natural seam --
everything here is about getting bytes from the network onto disk safely,
with no knowledge of Go/Deno/Zig/Wasmtime/Lua specifics.

These functions guard the moment a downloaded archive becomes an
executable on this machine, which is why both of them fail closed:
unverifiable digest means no install, and an archive member that resolves
outside the destination is refused rather than clamped.
"""
from __future__ import annotations

import hashlib
import shutil
import tarfile
import zipfile
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_digest(archive: Path, digest: str, *, runtime: str) -> str:
    """Verify a downloaded archive against its publisher digest. Fail closed.

    v4.163.0 (bug #51): all four install paths did

        expected = str(asset.get("digest") or "").split(":", 1)[-1]
        if expected and got.lower() != expected.lower():
            raise RuntimeError(...)

    -- so a MISSING digest silently skipped verification. Three of the
    five asset resolvers can return an empty one (`asset.get("digest")
    or ""`), which happens whenever the GitHub release API omits the
    field. The result was reproduced end to end: with `digest: ""` a
    hand-made archive containing `#!/bin/sh; echo TROJAN` installed as
    the `deno` executable and was registered as a managed runtime.

    That is the wrong direction for an unverifiable download. These
    archives are fetched over the network and then executed, so "we
    could not check it" has to mean "we do not install it".
    """
    got = _sha256(archive)
    expected = digest.split(":", 1)[-1].strip() if digest else ""
    if not expected:
        raise RuntimeError(
            f"refusing to install {runtime}: the publisher did not provide a "
            f"sha256 digest for {archive.name}, so the download cannot be "
            f"verified. Pass the expected digest explicitly if you have it "
            f"from a trusted source."
        )
    if got.lower() != expected.lower():
        raise RuntimeError(
            f"sha256 mismatch for {archive.name}: got {got}, expected {expected}")
    return got


def _safe_join_extract(base: Path, member_name: str) -> Path:
    target = (base / member_name).resolve()
    base_resolved = base.resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise RuntimeError(f"archive member escapes destination: {member_name}")
    return target


def _extract_zip_safe(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            target = _safe_join_extract(dest, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def _extract_tar_safe(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:*") as t:
        for member in t.getmembers():
            target = _safe_join_extract(dest, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = t.extractfile(member)
            if src is None:
                continue
            with src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
