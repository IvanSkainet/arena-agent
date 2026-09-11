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


class TokenFileVanishedError(OSError):
    """The installed token file was removed or replaced by someone else.

    The write itself succeeded, so this is deliberately *not* a
    `TokenFileModeWarning`: nothing usable is at the path, and a caller
    that treats it as a completed rotation would report success for a
    token that is not on disk.
    """

    def __init__(self, target: Path) -> None:
        super().__init__(
            f"{target} was removed or replaced by another process "
            "immediately after it was written; the rotation did NOT survive.")
        self.target = target


def _settle_by_descriptor(target: Path, fd: int) -> None:
    """Re-apply the mode through the descriptor we replaced into place.

    CodeRabbit, #211: resolving `target` by path a second time reopens the
    window the identity check exists to close -- a process that swaps the
    path between `os.replace` and `os.stat` gets its own file chmodded to
    0600 and its inode recorded as ours. The descriptor from before the
    rename cannot be redirected, so `os.fchmod` always lands on our file
    and `os.fstat` always reports our identity; only the path lookup can
    disagree, which is exactly the signal wanted.
    """
    mode_error: OSError | None = None
    try:
        os.fchmod(fd, 0o600)
    except OSError as exc:
        mode_error = exc
    try:
        at_path = os.stat(target).st_ino
    except OSError:
        raise TokenFileVanishedError(target) from mode_error
    if at_path != os.fstat(fd).st_ino:
        raise TokenFileVanishedError(target) from mode_error
    if mode_error is not None:
        raise TokenFileModeWarning(target, mode_error) from mode_error


def _settle_by_path(target: Path, installed: int | None) -> None:
    """The same settlement where a descriptor cannot survive the rename.

    Windows refuses to rename a file that is still open, so the descriptor
    is closed before `os.replace` there and the mode has to be re-applied
    by path. `installed` is the inode captured before the rename where the
    OS exposes a stable one, and `None` otherwise -- in which case only the
    file's disappearance is detectable, not a same-path swap.
    """
    mode_error: OSError | None = None
    try:
        os.chmod(target, 0o600)
    except OSError as exc:
        mode_error = exc
    try:
        current = os.stat(target).st_ino
    except OSError:
        raise TokenFileVanishedError(target) from mode_error
    if installed is not None and current != installed:
        raise TokenFileVanishedError(target) from mode_error
    if mode_error is not None:
        raise TokenFileModeWarning(target, mode_error) from mode_error


def _write_temp_beside(target: Path, token: str) -> tuple[Path, int]:
    """Write `token` to a fresh file next to `target`, returning its fd too.

    The descriptor stays open on purpose: it is what lets the caller act on
    the file it wrote rather than on whatever the path resolves to later.
    """
    fd, name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    with os.fdopen(os.dup(fd), "w", encoding="utf-8") as handle:
        handle.write(token)
        handle.flush()
        os.fsync(handle.fileno())
    return Path(name), fd


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
    fd = -1
    try:
        tmp, fd = _write_temp_beside(target, token)
        # By path, deliberately: the pre-replace chmod is the one callers
        # and tests exercise as "the write failed and nothing was
        # installed", and the temporary name is ours alone, so there is no
        # swap window to close here. The descriptor matters only after the
        # rename, where the path stops being a reliable handle.
        os.chmod(tmp, 0o600)
        fd = _replace_and_settle(tmp, target, fd)
    finally:
        _close_and_clean(fd, tmp)


def _replace_and_settle(tmp: Path, target: Path, fd: int) -> int:
    """Install `tmp` at `target` and re-apply the mode, returning the fd.

    The descriptor is closed and `-1` returned where it cannot survive the
    rename, so the caller's cleanup stays honest about what is still open.
    """
    installed = os.stat(tmp).st_ino if os.name == "posix" else None
    if not hasattr(os, "fchmod"):
        # Windows will not rename a file that is still open.
        os.close(fd)
        fd = -1
    os.replace(tmp, target)
    if fd >= 0:
        _settle_by_descriptor(target, fd)
    else:
        _settle_by_path(target, installed)
    return fd


def _close_and_clean(fd: int, tmp: Path | None) -> None:
    """Release the descriptor and remove the temporary file if it survived.

    After a successful `os.replace` the temporary name is already gone, so
    the unlink is only for the paths that failed before the rename.
    """
    if fd >= 0:
        os.close(fd)
    if tmp is None:
        return
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
