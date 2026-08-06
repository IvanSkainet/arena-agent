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


def _ensure_root(root: Path) -> dict[str, Any] | None:
    """Create the staging root, or return an envelope saying why not.

    v4.165.0 (bug #62), found by a surviving mutant: this was a bare
    `root.mkdir(parents=True, exist_ok=True)` whose exceptions nobody
    caught. Creating a directory is not a total operation -- a read-only
    parent gives PermissionError, a missing intermediate gives
    FileNotFoundError once `parents` is anything but True, a path
    component that is a file gives NotADirectoryError -- and every one of
    them escaped as an HTTP 500 while every other refusal on this path
    returns `{"ok": false}`. Same lesson as bug #43 (`Path.exists()` is
    not total), one function earlier in the same call chain.
    """
    try:
        root.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as e:
        return _err(
            f"could not create the staging directory: {e}",
            staging_root=str(root),
        )
    return None


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
    root_err = _ensure_root(root)
    if root_err is not None:
        return root_err
    # v4.162.0 (bug #42): `Path.expanduser()` raises an UNCAUGHT
    # RuntimeError("Could not determine home directory.") for a leading
    # `~unknownuser`, so `prepare("~nosuchuser/x.apk")` returned a 500
    # instead of a clean refusal. It is also wrong on its own terms here:
    # `~` is a legal filename character, and an uploaded file literally
    # named `~foo.apk` must resolve inside the staging root, not somewhere
    # under /home. Only expand it for paths the caller meant as absolute.
    # Only `~` and `~/...` are home references. `~anything-else` is a
    # FILENAME, and it must be treated as one on every platform.
    #
    # Deciding that by "did expanduser() raise?" was wrong and CI caught
    # it: POSIX raises RuntimeError for an unknown user, but Windows
    # happily expands `~literal-tilde.apk` to a path under C:\Users, so
    # the same input was a staging file on Linux and an escape attempt on
    # Windows. Matching on the shape of the string instead makes the
    # behaviour identical everywhere -- which is the whole point, since
    # the uploaded filename comes from the network, not from a shell.
    raw = Path(client_path)
    is_home_ref = client_path == "~" or client_path.startswith(("~/", "~\\"))
    if is_home_ref:
        try:
            expanded = raw.expanduser()
        except RuntimeError:
            return _err(
                "could not determine the home directory for "
                f"{client_path!r}",
                hint="Pass a path relative to the staging directory.",
            )
        p = expanded if expanded.is_absolute() else root / expanded
    else:
        p = raw
    if not p.is_absolute():
        p = root / p
    # `root.resolve(strict=False)` used to be called here too, on its own
    # line, with the result thrown away and a comment claiming it "will
    # raise if impossible". With strict=False it does not raise, so the
    # line was dead: mutmut flipped it to strict=True and no test noticed,
    # which is how dead code announces itself. The root is resolved once,
    # below, inside the same try.
    try:
        resolved = p.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
    except Exception as e:
        return _err(f"could not resolve apk_path: {e}")
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
