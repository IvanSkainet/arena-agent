#!/usr/bin/env python3
"""Create a release zip for an Arena Unified Bridge release.

Usage:
    python3 scripts/make_release_zip.py [version] [output_path]

Examples:
    python3 scripts/make_release_zip.py                  # auto-detect from arena/constants.py
    python3 scripts/make_release_zip.py 3.77.0
    python3 scripts/make_release_zip.py 3.77.0 /tmp/arena-agent-v3.77.0.zip

The output zip contains an `arena-bridge/` prefix matching the layout
established for the current release layout. Excludes development-only and runtime-state files
(see RELEASE.md for the full exclusion list).
"""
from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path

# Resolve repo root: this script lives in <repo>/scripts/
ROOT = Path(__file__).resolve().parent.parent

# Top-level directories/files to exclude entirely
EXCLUDE_TOP = {
    "tests", ".github", "dev", ".git", ".pytest_cache", ".vscode", ".idea",
    ".installer-backup", "backups", "logs", "missions", "reports",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_SUBDIRS = {"__pycache__", ".pytest_cache", "node_modules", ".mypy_cache"}
# Tool caches are named per tool and the set keeps growing (.ruff_cache
# arrived with ruff, .pyrefly_cache with pyrefly). Enumerating them by hand
# is how `.ruff_cache/` — 17 files, 316 KB of hashed blobs — shipped inside
# every release zip from v4.15.x onward. Any dot-directory ending in
# `_cache` or `-cache` is build residue, never a runtime asset.
CACHE_DIR_SUFFIXES = ("_cache", "-cache")
EXCLUDE_FILES = {
    "token.txt", "audit.jsonl", "bridge.log", "requests.jsonl",
    "facts.jsonl", "history.jsonl",
}
# Rotated runtime logs (logrotate-style: requests.jsonl.1, requests.jsonl.2,
# audit.jsonl.3, bridge.log.1, ...) must not ship either. Match on prefix so
# any rotation suffix is caught, not just the exact base name. (Found while
# cutting v4.83.0: a tracked requests.jsonl.2 leaked into the release zip.)
EXCLUDE_LOG_PREFIXES = ("requests.jsonl", "audit.jsonl", "bridge.log")
EXCLUDE_PATH_PATTERNS = (
    "queue/running/", "queue/done/", "queue/failed/",
    "memory/sessions/", "memory/facts.jsonl", "memory/history.jsonl",
)
EXCLUDE_EXTRA = {".DS_Store", "Thumbs.db"}


def detect_version() -> str:
    """Read VERSION from arena/constants.py without importing the package."""
    constants = ROOT / "arena" / "constants.py"
    text = constants.read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not m:
        raise SystemExit("ERROR: cannot find VERSION in arena/constants.py")
    return m.group(1)


def _is_cache_dir(name: str) -> bool:
    """True for dot-prefixed tool caches (.ruff_cache, .pyrefly_cache, ...)."""
    return name.startswith(".") and name.endswith(CACHE_DIR_SUFFIXES)


def should_exclude(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if not parts:
        return True
    if parts[0] in EXCLUDE_TOP:
        return True
    for p in parts:
        if p in EXCLUDE_SUBDIRS or _is_cache_dir(p):
            return True
    basename = parts[-1]
    if basename in EXCLUDE_FILES or basename in EXCLUDE_EXTRA:
        return True
    if any(basename.startswith(p) for p in EXCLUDE_LOG_PREFIXES):
        return True
    for suf in EXCLUDE_SUFFIXES:
        if basename.endswith(suf):
            return True
    for pat in EXCLUDE_PATH_PATTERNS:
        if pat in rel_path:
            return True
    return False


def main(argv: list[str]) -> int:
    version = argv[1] if len(argv) > 1 else detect_version()
    out = Path(argv[2]) if len(argv) > 2 else Path(f"/tmp/arena-agent-v{version}.zip")

    if out.exists():
        out.unlink()

    file_count = 0
    total_bytes = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [
                d for d in dirnames
                if d not in EXCLUDE_SUBDIRS and d not in EXCLUDE_EXTRA
                and not _is_cache_dir(d)
            ]
            for fn in filenames:
                abs_path = Path(dirpath) / fn
                rel_path = abs_path.relative_to(ROOT).as_posix()
                if should_exclude(rel_path):
                    continue
                arcname = f"arena-bridge/{rel_path}"
                zf.write(abs_path, arcname=arcname)
                file_count += 1
                total_bytes += abs_path.stat().st_size

    print(f"OK: created {out}")
    print(f"  version: v{version}")
    print(f"  files: {file_count}")
    print(f"  uncompressed: {total_bytes:,} bytes")
    print(f"  compressed:   {out.stat().st_size:,} bytes")
    print()
    print("Next steps (see RELEASE.md):")
    print(f"  gh release upload v{version} {out} --clobber")
    print(f"  cp {out} /tmp/arena-agent.zip")
    print(f"  gh release upload v{version} /tmp/arena-agent.zip --clobber  # README alias")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
