"""Safe storage primitive for bridge bearer-token files."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


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
        os.chmod(target, 0o600)
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
