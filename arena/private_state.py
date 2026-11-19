"""Atomic state publication with private POSIX modes.

Windows deployments must restrict the state root ACL to the service owner;
chmod does not replace an inherited Windows ACL. No partial JSON is published.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_replace = os.replace


def private_directory(path: Path) -> None:
    missing = []
    parent = path
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    for created in reversed(missing):
        created.chmod(0o700)
    # Tighten existing permissions without granting an owner permission that
    # the operator deliberately removed (e.g. a read-only token directory).
    path.chmod(0o700 if os.name == "nt" else path.stat().st_mode & 0o700)


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
