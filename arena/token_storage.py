"""Safe storage primitive for bridge bearer-token files."""
from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

_LOG = logging.getLogger("arena-bridge")

TOKEN_FILE_MODE = 0o600
"""Owner-only, the only mode a bearer-token file is ever given.

Corgea: the literal appeared at three call sites -- the pre-replace chmod
of the staged file and both post-replace settlements -- where one being
changed without the others is a silent permissions regression.
"""


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


def _classify_post_replace(
        target: Path, mode_error: OSError | None, still_ours: bool) -> None:
    """Turn the outcome of a post-replace mode change into the right type.

    Two answers matter once `os.replace` has run (#211), and a caller
    decides on them whether to keep the new token in memory:

    * the file is provably ours and only the mode is in doubt -- the
      rotation took, so `TokenFileModeWarning`. Raising a plain error here
      is the defect: the caller kept the old credential while the next
      restart read the new one off disk, locking every client out;
    * the path is gone or holds someone else's file -- nothing usable was
      installed, so `TokenFileVanishedError`, even when the mode change
      itself succeeded.
    """
    if not still_ours:
        raise TokenFileVanishedError(target) from mode_error
    if mode_error is not None:
        raise TokenFileModeWarning(target, mode_error) from mode_error


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
    mode_error = _attempt(lambda: os.fchmod(fd, TOKEN_FILE_MODE))
    at_path = _inode_of(target)
    _classify_post_replace(
        target, mode_error, at_path is not None and at_path == os.fstat(fd).st_ino)


def _settle_by_path(target: Path, installed: int | None) -> None:
    """The same settlement where a descriptor cannot survive the rename.

    Windows refuses to rename a file that is still open, so the descriptor
    is closed before `os.replace` there and the mode is re-applied by
    path. `installed` is the inode captured before the rename where the OS
    exposes a stable one, and `None` otherwise -- in which case only the
    file's disappearance is detectable, not a same-path swap.
    """
    mode_error = _attempt(lambda: os.chmod(target, TOKEN_FILE_MODE))
    current = _inode_of(target)
    _classify_post_replace(
        target, mode_error,
        current is not None and (installed is None or current == installed))


def _attempt(action: Callable[[], None]) -> OSError | None:
    """Run `action`, returning the `OSError` it raised rather than raising.

    The mode change has to be attempted before the identity check, but its
    failure is only classifiable once identity is known, so the error is
    carried rather than thrown.
    """
    try:
        action()
    except OSError as exc:
        return exc
    return None


def _inode_of(target: Path) -> int | None:
    """`target`'s inode, or `None` if it cannot be stat'd at all."""
    try:
        return os.stat(target).st_ino
    except OSError:
        return None


def _write_temp_beside(target: Path, token: str) -> tuple[Path, int]:
    """Write `token` to a fresh file next to `target`, returning its fd too.

    The descriptor stays open on purpose: it is what lets the caller act on
    the file it wrote rather than on whatever the path resolves to later.
    """
    fd, name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(os.dup(fd), "w", encoding="utf-8") as handle:
            handle.write(token)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # CodeRabbit, #211: the caller can only clean up what it was
        # handed, and a raise here means it was handed nothing. Repeated
        # failures would leak a descriptor each time, and an fsync failure
        # would leave a world-readable temporary file holding the freshly
        # generated token on disk.
        os.close(fd)
        try:
            Path(name).unlink()
        except OSError:
            # Corgea: swallowing this silently is how a file holding the
            # generated token sits on disk with nobody aware of it. The
            # unlink failure must not replace the write failure the caller
            # is about to see, so it is logged rather than raised.
            _LOG.warning(
                "could not remove the staged token file %s after a failed "
                "write; it may still hold the generated token", name,
                exc_info=True)
        raise
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
    staged: _StagedToken | None = None
    try:
        staged = _StagedToken(*_write_temp_beside(target, token))
        # By path, deliberately: the pre-replace chmod is the one callers
        # and tests exercise as "the write failed and nothing was
        # installed", and the temporary name is ours alone, so there is no
        # swap window to close here. The descriptor matters only after the
        # rename, where the path stops being a reliable handle.
        os.chmod(staged.path, TOKEN_FILE_MODE)
        _replace_and_settle(staged, target)
    finally:
        if staged is not None:
            staged.release()


class _StagedToken:
    """The temporary file a rotation is staged in, and its open descriptor.

    Ownership of the descriptor lives here rather than in a local variable
    because `os.replace` can raise after the descriptor has already been
    closed. An earlier revision tracked it by reassigning a local from a
    helper's return value, so a failed replace skipped the assignment and
    the cleanup closed an already-closed fd -- which is how a rotation
    that should have reported "the write failed, your old token is
    intact" reported an EBADF instead, on Windows only.
    """

    def __init__(self, path: Path, fd: int) -> None:
        self.path = path
        self.fd = fd

    def close_descriptor(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def release(self) -> None:
        """Drop the descriptor and the temporary name, if either survives.

        After a successful `os.replace` the name is already gone, so the
        unlink only matters for the paths that failed before the rename.
        """
        self.close_descriptor()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _replace_and_settle(staged: _StagedToken, target: Path) -> None:
    """Install the staged file at `target` and re-apply the mode."""
    installed = os.stat(staged.path).st_ino if os.name == "posix" else None
    if os.name != "posix":
        # Windows refuses to rename a file that is still open (WinError 32),
        # and its st_ino is not a stable identity anyway, so the descriptor
        # buys nothing there. Measured: keeping it open made every rotation
        # fail on all five windows-latest jobs. `os.fchmod` exists on 3.14
        # for Windows, so its presence is the wrong thing to test.
        staged.close_descriptor()
    os.replace(staged.path, target)
    if staged.fd >= 0:
        _settle_by_descriptor(target, staged.fd)
    else:
        _settle_by_path(target, installed)
