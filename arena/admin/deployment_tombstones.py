"""Obsolete release-owned files staged out by archive updates."""
from __future__ import annotations

from pathlib import Path

# Keep this list narrow: entries are product tombstones, never operator state.
REMOVED_RELEASE_TARGETS = ("version.json",)


def stage_release_tombstones(
    install_root: Path,
    *,
    backup_root: Path | None,
    timestamp: int,
) -> list[tuple[Path, Path]]:
    """Move tombstones into rollback storage and return restore pairs."""
    staged: list[tuple[Path, Path]] = []
    for name in REMOVED_RELEASE_TARGETS:
        destination = Path(install_root) / name
        if destination.is_dir():
            raise IsADirectoryError(
                f"release tombstone is a directory: {destination}"
            )
        if destination.exists() or destination.is_symlink():
            backup = (
                backup_root / name if backup_root is not None
                else Path(install_root) / f".{name}.old-{timestamp}"
            )
            destination.rename(backup)
            staged.append((backup, destination))
    return staged
