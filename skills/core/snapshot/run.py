#!/usr/bin/env python3
"""core/snapshot — comprehensive platform archive with manifest."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

HOME = Path.home()
ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(HOME / "arena-bridge"))).expanduser()

EXCLUDE_PATTERNS = ("token", "secret", ".key")


def excluded(name: str) -> bool:
    low = name.lower()
    return any(p in low for p in EXCLUDE_PATTERNS)


def collect_includes(include_logs: bool) -> list[tuple[Path, str]]:
    """Return [(absolute_path, arcname), ...]."""
    items: list[tuple[Path, str]] = []
    # directories (recursive)
    dirs = [
        (ROOT / "bin", "arena-bridge/bin"),
        (ROOT / "scripts", "arena-bridge/scripts"),
        (ROOT / "skills", "arena-bridge/skills"),
        (ROOT / "memory", "arena-bridge/memory"),
    ]
    if include_logs:
        dirs.append((ROOT / "logs", "arena-bridge/logs"))
    for src, arc in dirs:
        if not src.exists():
            continue
        for p in src.rglob("*"):
            if p.is_file() and not excluded(p.name):
                rel = p.relative_to(src)
                items.append((p, f"{arc}/{rel}"))
    # specific files
    singles = [
        (HOME / ".config/systemd/user/arena-local-bridge.service",
         "config/systemd/user/arena-local-bridge.service"),
        (HOME / ".config/systemd/user/arena-task-runner.service",
         "config/systemd/user/arena-task-runner.service"),
        (HOME / "arena-local-bridge/local_bridge.py",
         "arena-local-bridge/local_bridge.py"),
        (HOME / "arena-local-bridge/README_RU.md",
         "arena-local-bridge/README_RU.md"),
    ]
    if include_logs:
        audit = HOME / ".arena-local-bridge/audit.jsonl"
        if audit.exists():
            singles.append((audit, "arena-local-bridge/audit.jsonl"))
    for src, arc in singles:
        if src.exists() and not excluded(src.name):
            items.append((src, arc))
    return items


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--include-logs", action="store_true")
    args = ap.parse_args()

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.out:
        out_tgz = Path(os.path.expanduser(args.out))
    else:
        out_dir = ROOT / "backups"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_tgz = out_dir / f"snapshot-{stamp}.tgz"
    manifest_path = out_tgz.with_suffix(out_tgz.suffix + ".manifest.json")

    items = collect_includes(args.include_logs)
    total_bytes = 0
    with tarfile.open(out_tgz, "w:gz") as tar:
        for src, arc in items:
            tar.add(src, arcname=arc)
            total_bytes += src.stat().st_size
    try:
        out_tgz.chmod(0o600)
    except OSError:
        pass

    # Manifest
    sha = sha256_of(out_tgz)
    manifest = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "tarball": str(out_tgz),
        "sha256": sha,
        "file_count": len(items),
        "raw_total_bytes": total_bytes,
        "archive_bytes": out_tgz.stat().st_size,
        "include_logs": args.include_logs,
        "script_versions": {},
    }
    # quick script "versions" = sha256 prefix
    for fname in ("bin/agentctl",):
        p = ROOT / fname
        if p.exists():
            manifest["script_versions"][fname] = sha256_of(p)[:16]
    for p in (ROOT / "scripts").glob("*.py"):
        manifest["script_versions"][f"scripts/{p.name}"] = sha256_of(p)[:16]

    manifest_path.write_text(json.dumps(manifest, indent=2,
                                         ensure_ascii=False) + "\n",
                              encoding="utf-8")
    try:
        manifest_path.chmod(0o600)
    except OSError:
        pass
    print(str(out_tgz))
    return 0


if __name__ == "__main__":    sys.exit(main())
