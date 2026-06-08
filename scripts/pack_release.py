#!/usr/bin/env python3
"""Build a release ZIP for Arena Unified Bridge — safely.

Security model: the release contains ONLY git-tracked files plus a small set of
explicitly-added artifacts (the optional `cloudflared` binary and empty runtime
directory placeholders). Because every sensitive file (token.txt, users.json,
*.jsonl audit/request logs, *.log, *.db, .env, keys) is git-ignored, building
from the tracked-file list makes it structurally impossible to leak them.

A final assertion scans the produced archive for known-sensitive names and
aborts if any slipped in — belt and suspenders.

Usage:
    python scripts/pack_release.py [output.zip]

The repo root is auto-detected (parent of this script's directory) and can be
overridden with ARENA_RELEASE_DIR.
"""
from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_DIR = Path(os.environ.get("ARENA_RELEASE_DIR", Path(__file__).resolve().parents[1]))
DEFAULT_OUT = REPO_DIR / "arena-agent.zip"
ARCHIVE_ROOT = "arena-bridge"  # top-level folder name inside the zip

# Extra tracked files we never want in a release even though they are committed.
EXCLUDE_SUBPATHS = (
    ".github/",
    "dev/",            # stress-test harness — not needed by end users
    "tests/",
    "projects/test-project/",  # sample project, keep the release's projects/ clean
)

# Binaries fetched/built on the maintainer's machine that we DO want bundled
# (so end users get a true one-click experience) even though they are git-ignored.
BUNDLE_IF_PRESENT = ("cloudflared", "cloudflared.exe")

# Empty runtime directories shipped as placeholders.
PLACEHOLDER_DIRS = (
    "backups", "logs", "subagents", "missions", "projects",
    "reports/shots", "reports/snapshots", "reports/recordings",
    "queue/inbox", "queue/running", "queue/done", "queue/failed",
    "memory/sessions",
)

# Names that must NEVER appear in a release. Used by the final safety scan.
SENSITIVE_NAMES = ("token.txt", "users.json", ".env")
SENSITIVE_SUFFIXES = (".jsonl", ".log", ".db", ".pem", ".key", ".p12", ".pfx")
SENSITIVE_CONTAINS = ("id_rsa", "id_ed25519", ".git-credentials", ".aws/credentials", ".netrc")


def tracked_files(repo: Path) -> list[str]:
    """Return git-tracked file paths (relative, posix) for the repo."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def is_excluded(rel: str) -> bool:
    return any(rel == s.rstrip("/") or rel.startswith(s) for s in EXCLUDE_SUBPATHS)


def is_sensitive(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if name in SENSITIVE_NAMES:
        return True
    if any(name.endswith(suf) for suf in SENSITIVE_SUFFIXES):
        return True
    return any(token in rel for token in SENSITIVE_CONTAINS)


def pack(out_zip: Path) -> int:
    print("=== ARENA AGENT RELEASE PACKAGING ===")
    if not (REPO_DIR / ".git").exists() and not (REPO_DIR / "unified_bridge.py").exists():
        print(f"ERROR: {REPO_DIR} does not look like the arena-bridge repo")
        return 1

    try:
        files = tracked_files(REPO_DIR)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"ERROR: could not list tracked files via git: {e}")
        print("Release packaging requires a git checkout (safe-by-construction).")
        return 1

    if out_zip.exists():
        out_zip.unlink()
        print("Removed old release ZIP")

    written: list[str] = []
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            if is_excluded(rel):
                continue
            if is_sensitive(rel):
                # Should never happen (tracked + sensitive), but refuse loudly.
                print(f"  ! refusing sensitive tracked file: {rel}")
                continue
            fp = REPO_DIR / rel
            if not fp.is_file():
                continue
            arc = f"{ARCHIVE_ROOT}/{rel}"
            z.write(fp, arc)
            written.append(arc)

        for name in BUNDLE_IF_PRESENT:
            fp = REPO_DIR / name
            if fp.is_file():
                arc = f"{ARCHIVE_ROOT}/{name}"
                z.write(fp, arc)
                written.append(arc)
                print(f"  + {arc} (bundled binary)")

        for d in PLACEHOLDER_DIRS:
            arc = f"{ARCHIVE_ROOT}/{d}/.gitkeep"
            if arc in written:
                continue  # already shipped as a tracked file
            z.writestr(arc, "")
            written.append(arc)

    # --- Final safety scan: assert nothing sensitive made it in ---
    leaked = [a for a in written if is_sensitive(a)]
    if leaked:
        out_zip.unlink(missing_ok=True)
        print("ERROR: sensitive files detected in archive, aborting:")
        for a in leaked:
            print(f"   - {a}")
        return 2

    size_mb = out_zip.stat().st_size / (1024 * 1024)
    print(f"\n=== DONE ===")
    print(f"Release ZIP: {out_zip}")
    print(f"Files: {len(written)}  |  Size: {size_mb:.2f} MB")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(pack(target))
