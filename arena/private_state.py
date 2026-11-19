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
    """Create private components without path-based chmod after creation."""
    parent, missing = _missing_components(path)
    if os.name == "nt":
        _windows_private_directory(path)
        return
    _posix_private_components(parent, missing)


def _missing_components(path: Path) -> tuple[Path, list[str]]:
    missing = []
    parent = path.absolute()
    while not parent.exists():
        missing.append(parent.name)
        if parent == parent.parent:
            # Let an unavailable Windows drive/share produce its normal error.
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            return path, []
        parent = parent.parent
    return parent, missing


def _windows_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise OSError("refusing a symlink private directory")
    path.chmod(0o700)  # Deployment ACLs remain authoritative on Windows.


def _posix_private_components(parent: Path, missing: list[str]) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(parent, flags)
    try:
        for name in reversed(missing):
            try:
                os.mkdir(name, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass  # Verify through O_NOFOLLOW before touching its mode.
            child = os.open(name, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            os.fchmod(fd, os.fstat(fd).st_mode & 0o700)
        # Preserve deliberately removed owner bits; never grant new access.
        os.fchmod(fd, os.fstat(fd).st_mode & 0o700)
    finally:
        os.close(fd)


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
