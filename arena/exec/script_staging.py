"""Staging a /v1/exec/script body onto disk.

Its own module so `arena/exec/handlers.py` stays under the mini-monolith
line, and because where a script is written and how it is permissioned is
a separate question from how requests are gated.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["stage_script"]


def stage_script(root: Path, request_id: str, suffix: str) -> str:
    """Write the script body's file beside the root, owner-only.

    Scoped to `root` so a cross-mount delete cannot leak it, and through
    `mkstemp`, which is race-free and creates at mode 0o600.
    """
    tmp_dir = root / ".arena_script_tmp"
    tmp_dir.mkdir(exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f"scr-{request_id[:8]}-",
                                    suffix=suffix, dir=str(tmp_dir))
    os.close(fd)
    return tmp_path
