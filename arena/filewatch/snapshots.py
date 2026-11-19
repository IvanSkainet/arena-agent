"""Jailed file snapshots shared by watcher registration and polling."""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from arena.files.sandbox import validate_watch_target


def _matches(path: Path, patterns: list[str]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(path.name, pat) for pat in patterns)


@dataclass(frozen=True)
class SnapshotPolicy:
    recursive: bool
    patterns: list[str]
    max_files: int
    jail: tuple[Path, Path]


def _snapshot(path: Path, policy: SnapshotPolicy) -> tuple[dict[str, tuple[int, int]], bool]:
    root, home = policy.jail
    files: dict[str, tuple[int, int]] = {}
    resolved = _resolve_target(str(path), root=root, home=home)
    if resolved is None:
        return files, False
    if resolved.is_file():
        st = resolved.stat()
        files[str(path)] = (st.st_mtime_ns, st.st_size)
        return files, False
    return _directory_snapshot(path, resolved, policy)


def _directory_snapshot(display_path: Path, canonical_root: Path, policy: SnapshotPolicy) -> tuple[dict[str, tuple[int, int]], bool]:
    root, home = policy.jail
    files: dict[str, tuple[int, int]] = {}
    truncated = False
    iterator = canonical_root.rglob("*") if policy.recursive else canonical_root.glob("*")
    for entry in iterator:
        resolved = _resolve_target(str(entry), root=root, home=home)
        if resolved is None:
            continue
        if not resolved.is_file() or not _matches(entry, policy.patterns):
            continue
        st = resolved.stat()
        display_entry = display_path / entry.relative_to(canonical_root)
        files[str(display_entry)] = (st.st_mtime_ns, st.st_size)
        if len(files) >= policy.max_files:
            truncated = True
            break
    return files, truncated



def _resolve_target(target: str, *, root: Path, home: Path) -> Path | None:
    """Use the same jail as the HTTP handler; never raise on an invalid path."""
    path, _error, _status = validate_watch_target(target, root=root, home=home)
    if path is None:
        return None
    return _canonical_watch_target(path, root, home)


def _canonical_watch_target(path: Path, root: Path, home: Path) -> Path | None:
    try:
        canonical = path.resolve()
    except (OSError, RuntimeError):
        return None
    # Preserve original-name sensitivity above, then validate the captured
    # canonical target as well in case the link changed during resolution.
    resolved, _error, _status = validate_watch_target(str(canonical), root=root, home=home)
    return resolved
