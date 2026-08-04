"""Path containment for the APK staging area.

Split out of `apk_install.py` in v4.162.0: that module hit the 600-line
runtime cap while bugs #41-#43 were being fixed, and this is the natural
seam -- everything here is pure path arithmetic with no adb, no network
and no subprocess, so it is trivially testable on its own.

The rule these helpers enforce is simple and absolute: **nothing may be
read from or written to a location outside the staging root**, and the
check happens BEFORE anything touches the filesystem. Bug #41 was exactly
the opposite ordering -- the bytes were written, and only then did the
caller learn the destination was illegal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": msg, **extra}


def _staging_root() -> Path:
    from arena.mobile.apk_install import STAGING_ROOT
    return STAGING_ROOT


def _ensure_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)


def ensure_within_staging(dest: Path, root: Path) -> dict[str, Any] | None:
    """Return an error envelope if `dest` resolves outside `root`, else None.

    Resolves symlinks: a link planted inside the staging tree must not
    become a way out. Deleting this check lets an upload follow
    `staging/evil -> /some/real/dir` and write there (verified by
    sabotage; the guard test needs the link target to EXIST, otherwise
    mkdir fails for unrelated reasons and hides the escape).
    """
    root_resolved = root.resolve(strict=False)
    try:
        dest_resolved = dest.resolve(strict=False)
    except Exception as e:
        return _err(f"could not resolve destination: {e}")
    if root_resolved != dest_resolved and root_resolved not in dest_resolved.parents:
        return _err(
            "resolved destination escapes the staging directory",
            hint="A symlink inside the staging tree pointed outside it. "
                 "Nothing was written.",
            staging_root=str(root_resolved),
        )
    return None


def resolve_apk_path(client_path: str, staging_root: Path | None = None) -> Path | dict[str, Any]:
    """Reject path traversal. `client_path` may be:
      * absolute under root
      * relative — treated as relative to root
    Anything else is refused.
    """
    if not isinstance(client_path, str) or not client_path.strip():
        return _err("apk_path is required")
    root = staging_root if staging_root is not None else _staging_root()
    _ensure_root(root)
    # v4.162.0 (bug #42): `Path.expanduser()` raises an UNCAUGHT
    # RuntimeError("Could not determine home directory.") for a leading
    # `~unknownuser`, so `prepare("~nosuchuser/x.apk")` returned a 500
    # instead of a clean refusal. It is also wrong on its own terms here:
    # `~` is a legal filename character, and an uploaded file literally
    # named `~foo.apk` must resolve inside the staging root, not somewhere
    # under /home. Only expand it for paths the caller meant as absolute.
    raw = Path(client_path)
    if client_path.startswith("~"):
        try:
            expanded = raw.expanduser()
        except RuntimeError:
            # No such user -- so this was never a home-directory
            # reference, just a filename that happens to start with `~`.
            # Treat it as staging-relative rather than blowing up.
            expanded = raw
        p = expanded if expanded.is_absolute() else root / expanded
    else:
        p = raw
    if not p.is_absolute():
        p = root / p
    try:
        resolved = p.resolve(strict=False)
        root.resolve(strict=False)  # will raise if impossible
    except Exception as e:
        return _err(f"could not resolve apk_path: {e}")
    root_resolved = root.resolve(strict=False)
    if root_resolved not in resolved.parents and resolved != root_resolved:
        return _err(
            "apk_path must live under the staging directory",
            hint=f"Uploaded APKs go under {root}. Arbitrary host paths "
                 f"are rejected on purpose so a hijacked token can't install "
                 f"anything on disk.",
            staging_root=str(root),
        )
    # v4.162.0 (bug #43): `Path.exists()` is not total. A name longer than
    # NAME_MAX raises OSError(ENAMETOOLONG), and an embedded NUL raises
    # ValueError -- both escaped as exceptions and became HTTP 500s while
    # every other rejection on this path returns an {"ok": false} envelope.
    # An endpoint that fails closed must do so for hostile input too, not
    # just for the inputs someone thought of.
    try:
        exists = resolved.exists()
        is_file = resolved.is_file()
    except (OSError, ValueError) as e:
        return _err(f"invalid apk_path: {e}")
    if not exists:
        return _err(
            f"apk not found: {resolved}",
            hint="Upload the APK first (POST it to root); then call "
                 "prepare with the returned path.",
        )
    if not is_file:
        return _err(f"apk_path is not a regular file: {resolved}")
    return resolved
