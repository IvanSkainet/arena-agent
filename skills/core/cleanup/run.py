#!/usr/bin/env python3
"""core/cleanup — prune old backups, sessions, reports, completed tasks."""
from __future__ import annotations
import argparse
import os
import time
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME",
                           str(Path.home() / "arena-bridge"))).expanduser()

CATEGORIES = [
    ("backups", ROOT / "backups", ("*.tgz", "*.tar.gz")),
    ("sessions", ROOT / "memory" / "sessions", ("*.jsonl",)),
    ("reports", ROOT / "reports", ("*.md", "*.json", "*.html")),
    ("queue_done", ROOT / "queue" / "done", ("*.json",)),
    ("queue_failed", ROOT / "queue" / "failed", ("*.json",)),
]


def collect(d: Path, patterns: tuple[str, ...]) -> list[Path]:
    if not d.is_dir():
        return []
    files: list[Path] = []
    for pat in patterns:
        files.extend(d.glob(pat))
    # exclude symlinks (e.g. memory/sessions/current)
    return [f for f in files if f.is_file() and not f.is_symlink()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--keep", type=int, default=10)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    cutoff = time.time() - args.days * 86400
    grand_freed = 0
    for name, d, patterns in CATEGORIES:
        files = collect(d, patterns)
        if not files:
            print(f"{name:14}  (empty)")
            continue
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        # newest `keep` are always kept regardless of age
        keep_set = set(files[: args.keep])
        old = [f for f in files if f not in keep_set and f.stat().st_mtime < cutoff]
        kept = len(files) - len(old)
        bytes_to_free = sum(f.stat().st_size for f in old)
        print(f"{name:14}  total={len(files):3d}  keep={kept:3d}  prune={len(old):3d}  "
              f"freed={bytes_to_free} bytes"
              + ("  [dry-run]" if args.dry_run else ""))
        if not args.dry_run:
            for f in old:
                try:
                    f.unlink()
                except OSError as e:
                    print(f"  warn: could not delete {f.name}: {e}")
            grand_freed += bytes_to_free
    if not args.dry_run:
        print(f"--- total freed: {grand_freed} bytes ---")
    else:
        print("--- dry run, pass --apply to actually delete ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
