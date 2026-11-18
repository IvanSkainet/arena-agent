"""Atomic owner-only state publication; no incomplete JSON becomes visible."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_replace = os.replace


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def write_private_json(path: Path, value: Any, *, replace: bool = True) -> None:
    private_directory(path.parent)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix="." + path.name, suffix=".tmp")
    staged = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            _replace(staged, path)
        else:
            os.link(staged, path)
        path.chmod(0o600)
    finally:
        staged.unlink(missing_ok=True)
