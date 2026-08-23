"""Release-archive download + digest verification for auto-update.

Split out of `auto_update.py` in v4.164.0: that module crossed the
600-line runtime cap while bug #61 was being fixed, and this is the
natural seam -- fetching bytes and checking a hash knows nothing about
version comparison, consent tokens, or the platform-specific install
swap.

The rule this file exists to enforce: an archive that is about to
replace the bridge's own code is verified, or it is refused. Skipping
that is a decision a caller states out loud (`allow_unverified=True`),
never something an empty argument causes.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from arena.security_http import open_public_url

_MAX_RELEASE_SIZE_BYTES = 512 * 1024 * 1024


class _TooLarge(Exception):
    """Size cap tripped mid-stream.

    Raised rather than returned so the open file handle is closed by the
    `with` block before the staging tree is removed -- on Windows an open
    handle blocks rmtree, which would silently re-leak the directory the
    cleanup exists to reclaim.
    """

_DOWNLOAD_CHUNK_SIZE_BYTES = 1024 * 1024


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    """Local copy of the module-level error shape.

    Imported from auto_update.py would be circular: that module imports
    these functions. The shape is three lines and stable since v4.43.0.
    """
    res: dict[str, Any] = {"ok": False, "error": msg}
    res.update(extra)
    return res


def _user_agent() -> str:
    from arena.admin.auto_update import _USER_AGENT
    return _USER_AGENT


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_DOWNLOAD_CHUNK_SIZE_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


def _discard_staging(dest: Path, owned: bool) -> None:
    """Remove a staging tree this function created, on a failure path only.

    `owned` is the whole point. When the caller passed `dest_dir` the
    directory is theirs -- it may be an install-managed staging root with
    other content -- and deleting it would destroy data this function was
    merely borrowing. Only the `mkdtemp` we made ourselves is ours to remove.

    Never called on success: on Windows the detached mover copies *from*
    staging after the bridge process exits, so the tree has to outlive us
    (see #160, and the constraint recorded in `auto_update_windows.py`).

    Best-effort by design. A cleanup failure must not convert a reported
    download error into a raised exception -- the caller needs the real
    reason the update did not happen, not an errno from the janitor.

    `ignore_errors=True` is the entire error policy. An outer try/except/pass
    around it would be dead code that could only ever swallow a *different*
    fault (flagged as B110 in review on #170), so there is deliberately none:
    if rmtree itself is ever replaced with something that can raise, that
    should surface rather than hide here.
    """
    if not owned:
        return
    shutil.rmtree(dest, ignore_errors=True)


def download_release(*, asset_url: str, asset_name: str,
                     expected_sha256: str | None = None,
                     allow_unverified: bool = False,
                     dest_dir: Path | str | None = None) -> dict[str, Any]:
    """Download a release zip to `dest_dir` and verify its SHA-256.

    `expected_sha256` accepts the `sha256:...` prefix GitHub returns.

    v4.164.0 (bug #61): verification was two nested truthiness checks
    (`if expected_sha256:` then `if want and ...`), so `None`, `""`,
    `"   "`, `"sha256:"` and `"sha256:   "` all meant "install whatever
    arrived" -- confirmed by execution. `apply_update()` does gate the
    unverified path with its own opt-in, but this is module-level API and
    a bare call here reads as if it verifies. Skipping the check is now
    something a caller states, not something an empty argument causes.
    """
    if not asset_url or not asset_name:
        return _err("asset_url and asset_name are required")
    # v4.169.51 (#160): `owned` tracks whether this call created the staging
    # tree. Every early return below used to leak it -- the directory is made
    # before the SSRF check and before a single byte is fetched, so a rejected
    # URL, a DNS failure, an oversized archive or a digest mismatch each left
    # an empty `arena-update-*` behind forever. Measured on the operator's
    # machine: 191 trees, 185 of them empty, accumulating ~4-8 per day.
    # `owned` must follow the *same* test that decides whether mkdtemp runs.
    # `dest_dir is None` diverged from `if dest_dir`: a falsey non-None value
    # ("" or Path("")) created a temp tree and then marked it not-ours, so it
    # was never reclaimed. Raised independently by two reviewers on #170.
    owned = not dest_dir
    dest = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="arena-update-"))
    dest.mkdir(parents=True, exist_ok=True)
    # try/finally is the guarantee. Cleaning up at each `return _err` covered
    # only the paths someone remembered: an exception out of _sha256_of -- a
    # disk read error after the bytes landed -- still leaked, and any early
    # return added later would leak again. Reclaiming is now the default and
    # success is the single explicit opt-out. Both gaps were reproduced before
    # fixing; raised by sourcery, codacy and qodo on #170.
    result = _err("download did not run")
    try:
        result = _download_into(
            dest=dest,
            asset_url=asset_url,
            asset_name=asset_name,
            expected_sha256=expected_sha256,
            allow_unverified=allow_unverified,
        )
        return result
    finally:
        if not result.get("ok"):
            _discard_staging(dest, owned)


def _download_into(*, dest: Path, asset_url: str, asset_name: str,
                   expected_sha256: str | None,
                   allow_unverified: bool) -> dict[str, Any]:
    """Fetch and verify into an already-created `dest`.

    Split out so `download_release` can wrap the whole thing in one
    try/finally: the cleanup decision then depends only on the returned
    `ok`, and no future early return can bypass it.
    """
    zip_path = dest / asset_name
    try:
        # v4.43.0: SSRF + size-cap defence for the release
        # download. asset_url is fed from the /v1/update  # nosec B310 -- inspected -- fixed / SSRF-guarded URL
        # endpoint which already restricts sources, but a
        # compromised upstream (or a badly-configured
        # allowlist) shouldn't be able to stream unlimited
        # bytes into the operator's disk. 512 MiB is well over
        # a real release (~3 MB); an archive that big is
        # already something we don't want to install.
        from arena.security_ssrf import _validate_url
        ssrf_err = _validate_url(asset_url)
        if ssrf_err:
            return _err(f"asset_url rejected: {ssrf_err}",
                        asset_url=asset_url)
        req = urllib.request.Request(asset_url, headers={"User-Agent": _user_agent()})
        with open_public_url(req, timeout=60) as resp, zip_path.open("wb") as out:
            written = 0
            while True:
                chunk = resp.read(_DOWNLOAD_CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_RELEASE_SIZE_BYTES:
                    raise _TooLarge()
                out.write(chunk)
    except _TooLarge:
        return _err("release zip exceeded 512 MiB size cap",
                    asset_url=asset_url)
    except Exception as e:
        return _err(f"download failed: {e!r}", asset_url=asset_url)

    got = _sha256_of(zip_path)
    want = (expected_sha256 or "").split(":", 1)[-1].strip().lower()
    if not want:
        if not allow_unverified:
            return _err(
                "expected_sha256 is required: refusing to hand back an "
                "unverified release archive",
                got=got, path=str(zip_path),
                hint=("Pass the digest GitHub publishes for the asset, or "
                      "pass allow_unverified=True to accept the risk "
                      "deliberately."),
            )
    elif want != got:
        return _err("sha256 mismatch after download",
                    expected=want, got=got, path=str(zip_path))
    return {
        "ok": True,
        "path": str(zip_path),
        "sha256": got,
        "verified": bool(want),
        "size_bytes": zip_path.stat().st_size,
        "staging_dir": str(dest),
    }
