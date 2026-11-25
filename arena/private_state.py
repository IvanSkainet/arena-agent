"""Atomic state publication with private POSIX modes.

Windows deployments must restrict the state root ACL to the service owner;
chmod does not replace an inherited Windows ACL. No partial JSON is published.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from arena.private_paths import create_staged_file, directory_matches, pinned_directory, unlink_staged

_replace = os.replace
# ERROR_ACCESS_DENIED and ERROR_SHARING_VIOLATION: what Windows answers while
# another handle still has the file open. POSIX errors carry no winerror.
_HELD_OPEN = frozenset({5, 32})
_HELD_OPEN_PATIENCE = 2.0


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
    with pinned_directory(path):
        path.chmod(0o700)  # Deployment ACLs remain authoritative on Windows.


def _posix_private_components(parent: Path, missing: list[str]) -> None:
    target = parent.joinpath(*reversed(missing))
    with pinned_directory(target) as fd:
        if fd is None:
            raise OSError("directory descriptors unavailable for POSIX private state")
        # The descriptor pins '.', even if a shared ancestor is renamed.
        # Preserve removed owner bits and do not require directory read access.
        mode = os.fstat(fd).st_mode & 0o700
        os.chmod(".", mode, dir_fd=fd, follow_symlinks=False)


def write_private_json(path: Path, value: Any, *, replace: bool = True) -> None:
    with pinned_directory(path.parent) as parent_fd:
        if parent_fd is None:
            _windows_private_directory(path.parent)
        else:
            os.chmod(".", os.fstat(parent_fd).st_mode & 0o700,
                        dir_fd=parent_fd, follow_symlinks=False)
        fd, staged = create_staged_file(path, parent_fd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            _publish(staged, path, replace, parent_fd)
            if not directory_matches(path.parent, parent_fd):
                raise OSError("private publication parent changed")
        finally:
            try:
                unlink_staged(staged, parent_fd)
            except FileNotFoundError:
                pass


def _publish(staged: Path, target: Path, replace: bool, parent_fd: int | None) -> None:
    source = staged if parent_fd is None else staged.name
    destination = target if parent_fd is None else target.name
    kwargs = {} if parent_fd is None else {"src_dir_fd": parent_fd, "dst_dir_fd": parent_fd}
    if replace:
        _replace_once_released(source, destination, **kwargs)
    else:
        os.link(source, destination, follow_symlinks=False, **kwargs)


def _replace_once_released(source: Any, destination: Any, **kwargs: Any) -> None:
    """Replace a file that a reader may have open for a moment (#581).

    Windows refuses to replace a file while any other handle has it open, so
    one status poll at the wrong moment lost the final state of a run for
    good. A refusal of that kind is tried again for a bounded time; every
    other error, and a file still held at the limit, is raised unchanged.
    """
    deadline = time.monotonic() + _HELD_OPEN_PATIENCE
    pause = 0.005
    while True:
        try:
            _replace(source, destination, **kwargs)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in _HELD_OPEN or time.monotonic() >= deadline:
                raise
        time.sleep(pause)
        pause = min(pause * 2, 0.05)
