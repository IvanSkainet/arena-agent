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


def write_owner_token(target: Path, token: str) -> None:
    """Atomically write an owner-only token file without following links.

    The target is refused when it is already a symlink. A uniquely named
    temporary file is written, flushed, synced and chmodded before replace;
    the mode is applied again after rename for filesystems that reset it.
    Any failure propagates so callers cannot report a successful rotation with
    an unprotected or partially written file.
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
        try:
            os.chmod(target, 0o600)
        except OSError as exc:
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
