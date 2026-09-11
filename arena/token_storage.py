"""Safe storage primitive for bridge bearer-token files."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


class TokenFileModeWarning(Exception):
    """The token was written, but its mode could not be re-applied.

    Raised *after* `os.replace` has already installed the new contents, so
    a caller must treat the rotation as having happened -- see #211. It is
    a distinct type precisely so callers can tell "nothing was written"
    from "written, but check the permissions".
    """

    def __init__(self, target: Path, cause: BaseException) -> None:
        super().__init__(
            f"token written to {target}, but its mode could not be set to "
            f"0600 ({type(cause).__name__}: {cause}). The rotation DID "
            f"take effect; check the file's permissions.")
        self.target = target


def _reject_if_not_still_ours(
        target: Path, installed: int | None, cause: OSError) -> None:
    """Re-raise `cause` unless `target` is still the file we just installed.

    The post-replace chmod is only downgraded to a warning because the new
    token is known to be on disk. If another process removed or replaced
    the path in the window between `os.replace` and `os.chmod`, that is no
    longer true: reporting success would hand back a token that vanishes
    on the next restart (cubic, #211). The inode is compared where the OS
    exposes a stable one, and mere existence elsewhere.
    """
    try:
        current = os.stat(target)
    except OSError:
        raise cause from None
    if installed is not None and current.st_ino != installed:
        raise cause from None


def write_owner_token(target: Path, token: str) -> None:
    """Atomically write an owner-only token file without following links.

    The target is refused when it is already a symlink. A uniquely named
    temporary file is written, flushed, synced and chmodded before replace;
    the mode is applied again after rename for filesystems that reset it.

    Failures before and during `os.replace` propagate, so a caller cannot
    report a successful rotation over an unprotected or partially written
    file. The single exception is the re-chmod that runs *after* a replace
    that already succeeded: the new token is the file's contents by then,
    so raising a plain error there would make the caller keep the old
    credential in memory while the next restart reads the new one off disk
    (#211). That case raises `TokenFileModeWarning`, which callers are
    expected to treat as "rotated, now go check the permissions" rather
    than as a failed write -- do not turn it back into a hard failure.
    Every other post-replace problem, including the file having been
    removed or swapped underneath us, is still a hard error.
    """
    if target.is_symlink():
        raise OSError("refusing to replace a symlink token path")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
            delete=False,
        ) as handle:
            tmp = Path(handle.name)
            handle.write(token)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        installed = os.stat(target).st_ino if os.name == "posix" else None
        try:
            os.chmod(target, 0o600)
        except OSError as exc:
            _reject_if_not_still_ours(target, installed, exc)
            # #211 (cubic): past this point the new token IS the file's
            # contents -- `os.replace` is atomic and has already happened.
            # Raising here told the caller the rotation failed, so it kept
            # the old credential in memory while the next restart would
            # read the new one off disk and lock every client out.
            #
            # The re-chmod is belt-and-braces for filesystems that reset
            # the mode on rename; the mode was already applied to the
            # temporary file before the replace, so failing to re-apply it
            # is not a reason to call a completed rotation a failure. It is
            # worth knowing about, so it is raised as a warning that names
            # the file rather than swallowed.
            raise TokenFileModeWarning(target, exc) from exc
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
