"""Staging a /v1/exec/script body onto disk.

Its own module so `arena/exec/handlers.py` stays under the mini-monolith
line, and because where a script is written and how it is permissioned is
a separate question from how requests are gated.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from pathlib import Path

__all__ = ["stage_script"]

def _name_fragment(request_id: str) -> str:
    """A short, filename-safe stand-in for a client-controlled id.

    `request_id` arrives in `X-Arena-Request-Id` and used to be spliced
    into the filename after a regex stripped the dangerous characters.
    That was sound -- separators could not survive it -- but it left
    client data on a filesystem path, which CodeQL reports as
    `py/path-injection` (2 high alerts, #346) because it does not model
    the regex as a sanitiser. A permanently-red required security gate
    is worse than the argument is worth, and there is a construction
    with nothing to argue about: hash the id.

    The output is hex, so it cannot contain a separator, cannot be `..`
    and has a fixed length whatever arrives. It is still deterministic,
    so the same request keeps the same staged filename, and the audit
    event records both the id and the path when the two need joining.
    """
    return hashlib.sha256(request_id.encode("utf-8", "surrogatepass")
                          ).hexdigest()[:8]


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
    fd, tmp_path = tempfile.mkstemp(prefix=f"scr-{_name_fragment(request_id)}-",
                                    suffix=suffix, dir=str(tmp_dir))
    os.close(fd)
    return tmp_path
