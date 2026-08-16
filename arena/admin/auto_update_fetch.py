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
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

_MAX_RELEASE_SIZE_BYTES = 512 * 1024 * 1024
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
    dest = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="arena-update-"))
    dest.mkdir(parents=True, exist_ok=True)
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
        with urllib.request.urlopen(req, timeout=60) as resp, zip_path.open("wb") as out:  # nosec B310 -- SSRF-validated above; scheme forced to http/https by _validate_url  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
            written = 0
            while True:
                chunk = resp.read(_DOWNLOAD_CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_RELEASE_SIZE_BYTES:
                    return _err("release zip exceeded 512 MiB size cap",
                                asset_url=asset_url)
                out.write(chunk)
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
