"""File path sandbox helpers for upload/download endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_home_path(target: str, *, root: Path, home: Path) -> tuple[Path | None, str | None, int]:
    if not target:
        return None, "missing path", 400
    if ".." in Path(target).parts:
        return None, "path traversal not allowed", 400
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = root / target_path
    try:
        target_path.resolve().relative_to(home.resolve())
    except ValueError:
        return None, "path outside home directory", 403
    return target_path, None, 200


def validate_upload_target(target: str, *, root: Path, home: Path, bridge_py: Path) -> tuple[Path | None, str | None, int]:
    target_path, err, status = resolve_home_path(target, root=root, home=home)
    if err:
        if err == "path outside home directory":
            return None, "upload path must be inside user home", status
        return None, err, status
    if target_path.resolve() == bridge_py.resolve():
        return None, "cannot overwrite the bridge itself", 403
    return target_path, None, 200


def validate_download_target(target: str, *, root: Path, home: Path) -> tuple[Path | None, str | None, int]:
    target_path, err, status = resolve_home_path(target, root=root, home=home)
    if err:
        return None, err, status
    if not target_path.exists() or not target_path.is_file():
        return None, "file not found", 404
    return target_path, None, 200
