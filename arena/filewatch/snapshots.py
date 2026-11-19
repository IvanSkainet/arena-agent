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
    if _resolve_target(str(path), root=root, home=home) is None:
        return files, False
    if path.is_file():
        st = path.stat()
        files[str(path)] = (st.st_mtime_ns, st.st_size)
        return files, False
    return _directory_snapshot(path, policy)


def _directory_snapshot(path: Path, policy: SnapshotPolicy) -> tuple[dict[str, tuple[int, int]], bool]:
    root, home = policy.jail
    files: dict[str, tuple[int, int]] = {}
    truncated = False
    iterator = path.rglob("*") if policy.recursive else path.glob("*")
    for entry in iterator:
        if _resolve_target(str(entry), root=root, home=home) is None:
            continue
        if not entry.is_file() or not _matches(entry, policy.patterns):
            continue
        st = entry.stat()
        files[str(entry)] = (st.st_mtime_ns, st.st_size)
        if len(files) >= policy.max_files:
            truncated = True
            break
    return files, truncated



def _resolve_target(target: str, *, root: Path, home: Path) -> Path | None:
    """Use the same jail as the HTTP handler; never raise on an invalid path."""
    resolved, _error, _status = validate_watch_target(target, root=root, home=home)
    return resolved
