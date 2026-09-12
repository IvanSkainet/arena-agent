"""Staging a /v1/exec/script body onto disk.

Its own module so `arena/exec/handlers.py` stays under the mini-monolith
line, and because where a script is written and how it is permissioned is
a separate question from how requests are gated.
"""
from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path

__all__ = ["stage_script"]

# Everything outside this is dropped from the filename. `request_id` is
# client-controlled (`X-Arena-Request-Id`), and mkstemp treats a prefix
# containing a separator as nested path components: a request id of
# `a/b/c` asked it to create `scr-a/b/c-XXXX.py` under a directory that
# does not exist, so the endpoint answered 500 (cubic).
_UNSAFE_IN_NAME = re.compile(r"[^A-Za-z0-9._-]")


def stage_script(root: Path, request_id: str, suffix: str) -> str:
    """Create the empty owner-only file a script body will be written to.

    Returns its path; writing the bytes is the caller's job. The file is
    made by `mkstemp`, which is race-free and creates at mode 0o600, in a
    `.arena_script_tmp` directory under `root` -- inside the same
    filesystem as the root so a cross-mount delete cannot leak it.
    """
    tmp_dir = root / ".arena_script_tmp"
    tmp_dir.mkdir(exist_ok=True)
    # mkstemp gives the *file* 0o600, but the directory is born with
    # whatever the umask allows -- 0o755 under the common 0o022, which
    # lets any local user list the staged request ids. chmod covers the
    # directory this call just created and one left by an earlier run.
    # Not best-effort on POSIX: silently continuing with a world-readable
    # directory would keep the owner-only contract in the docstring and
    # nowhere else (cubic). Windows has no POSIX modes to set, so there
    # the chmod is genuinely not applicable and is skipped.
    if os.name == "posix":
        tmp_dir.chmod(0o700)
    else:
        with contextlib.suppress(OSError, NotImplementedError):
            tmp_dir.chmod(0o700)
    safe_id = _UNSAFE_IN_NAME.sub("-", request_id)[:8] or "anon"
    fd, tmp_path = tempfile.mkstemp(prefix=f"scr-{safe_id}-",
                                    suffix=suffix, dir=str(tmp_dir))
    os.close(fd)
    return tmp_path
