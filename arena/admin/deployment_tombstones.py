"""Obsolete release-owned files removed by archive updates."""
from __future__ import annotations

from pathlib import Path

# Keep this list narrow: entries are product tombstones, never operator state.
REMOVED_RELEASE_TARGETS = ("version.json",)


def remove_release_tombstones(install_root: Path) -> tuple[str, ...]:
    """Delete obsolete release files and refuse directory-shaped surprises."""
    removed: list[str] = []
    for name in REMOVED_RELEASE_TARGETS:
        path = Path(install_root) / name
        if path.is_dir():
            raise IsADirectoryError(f"release tombstone is a directory: {path}")
        if path.exists():
            path.unlink()
            removed.append(name)
    return tuple(removed)
