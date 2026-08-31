"""Restrict a file's permissions, and say so when it does not work.

Eight call sites tightened a file to owner-only with a bare
``os.chmod(path, 0o600)`` wrapped in ``except Exception: pass``. The
intent is right -- the audit log, the memory database and the rotated
log files hold operator data and should not be world-readable -- but a
swallowed failure turns a security control into a wish. Nothing is
logged, nothing is returned, and the file stays at whatever mode it had.

Some of those failures are expected and uninteresting: a filesystem that
does not implement POSIX modes (FAT, exFAT, many network mounts) raises
and there is nothing to be done about it. Those must not become noise.
A failure that is *not* that -- a permission error, a vanished file, a
read-only mount -- is a real finding and is worth a warning.

This helper draws that line once instead of at every call site.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

_log = logging.getLogger(__name__)

#: Modes that only the owner can read. Used to decide whether a failure
#: means "this file is more exposed than intended".
_OWNER_ONLY = stat.S_IRWXG | stat.S_IRWXO


def restrict(path: str | os.PathLike[str], mode: int, *, what: str = "") -> bool:
    """Apply ``mode`` to ``path``. Return True if it now holds.

    Never raises: callers use this on a best-effort basis, and a failure
    to tighten permissions must not take down the write that preceded it.
    The difference from a bare ``except Exception: pass`` is that the
    failure is *visible* -- logged at WARNING when the file is left more
    permissive than asked for, and the caller can act on the return value.
    """
    target = Path(path)
    label = what or str(target)
    try:
        os.chmod(target, mode)
    except NotImplementedError:
        # A filesystem without POSIX modes. Expected, not actionable.
        _log.debug("chmod not supported for %s; leaving mode as-is", label)
        return False
    except OSError as exc:
        if _leaves_file_exposed(target, mode):
            _log.warning(
                "could not restrict %s to %o (%s); the file may be readable "
                "by other users on this machine", label, mode, exc,
            )
        else:
            _log.debug("chmod failed for %s (%s)", label, exc)
        return False
    return True


def _leaves_file_exposed(target: Path, mode: int) -> bool:
    """True when the caller wanted owner-only but the file is not.

    A chmod failure only matters if the file is *currently* readable by
    someone the caller wanted to exclude. If the mode is already tight --
    because the umask or the parent directory got there first -- the
    failure is harmless and should stay at debug level.
    """
    if mode & _OWNER_ONLY:
        return False  # the caller was not asking for owner-only
    try:
        current = target.stat().st_mode
    except OSError:
        return False  # the file is gone; nothing is exposed
    return bool(current & _OWNER_ONLY)
