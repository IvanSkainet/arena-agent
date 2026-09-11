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


def _still_ours(target: Path, installed: int | None) -> bool:
    """Is `target` still the file `os.replace` just installed?

    Reporting a rotation as done means claiming the new token is what the
    path holds. If another process removed or replaced it in the window
    after `os.replace`, that claim is false and the caller would be handed
    a token that vanishes on the next restart (cubic, #211). The inode is
    compared where the OS exposes a stable one, and mere existence
    elsewhere.
    """
    try:
        current = os.stat(target)
    except OSError:
        return False
    return installed is None or current.st_ino == installed


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


def _settle_after_replace(target: Path) -> None:
    """Re-apply the mode after a rename and classify what can go wrong.

    Exactly two things are worth telling apart once `os.replace` has run
    (#211), because a caller decides on this whether to keep the new token
    in memory:

    * the file is ours and only the mode is in doubt -- the rotation took,
      so this is a `TokenFileModeWarning`, not a failure. Raising a plain
      error here left the caller on the old credential while the next
      restart read the new one off disk, locking every client out;
    * the path is gone or now holds someone else's file -- nothing usable
      was installed, so this is a hard `TokenFileVanishedError` even when
      the chmod itself succeeded.

    The re-chmod is belt-and-braces for filesystems that reset the mode on
    rename; the temporary file was already chmodded before the replace.
    """
    installed = os.stat(target).st_ino if os.name == "posix" else None
    mode_error: OSError | None = None
    try:
        os.chmod(target, 0o600)
    except OSError as exc:
        mode_error = exc
    # Identity is checked whether or not the chmod raised: a chmod that
    # succeeded on a path another process has since replaced says nothing
    # about our token still being there (cubic, #211).
    if not _still_ours(target, installed):
        raise TokenFileVanishedError(target) from mode_error
    if mode_error is not None:
        raise TokenFileModeWarning(target, mode_error) from mode_error


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
        _settle_after_replace(target)
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
