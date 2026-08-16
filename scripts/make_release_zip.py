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

import json
import os
import re
import stat
import subprocess  # nosec B404 -- fixed argv git query
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
    # pytest-cov writes this ignored file at the repository root. v4.169.43's
    # first clean-tag build still packed its 1.9 MB local report because the
    # old untracked guard deliberately did not inspect git-ignored files.
    "coverage.xml",
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

# ZIP headers otherwise inherit checkout wall-clock mtimes and host filesystem
# modes, so two clean runners produce different bytes for the same commit.
# DOS ZIP timestamps cannot represent dates before 1980.
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
SUPPORTED_GIT_FILE_MODES = frozenset({"100644", "100755"})
RELEASE_PROVENANCE = ".arena-release-provenance.json"
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_RUN_RE = re.compile(r"[1-9][0-9]*")


def detect_version() -> str:
    """Read VERSION from arena/constants.py without importing the package."""
    constants = ROOT / "arena" / "constants.py"
    text = constants.read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not m:
        raise SystemExit("ERROR: cannot find VERSION in arena/constants.py")
    return m.group(1)


# Dot-directories that are tool state rather than shipped content. The
# suffix rule alone was not enough: `.hypothesis` (600 files of generated
# example databases) matches neither `_cache` nor `-cache`, and rode along in
# the v4.158.0 build until the file count jumped from 1027 to 1629. Named
# entries cover the ones whose authors did not use a `cache` suffix.
CACHE_DIR_NAMES = frozenset({
    ".hypothesis",     # property-test example database
    ".tox", ".nox",    # environment matrices
    ".coverage",       # coverage data dir on some layouts
    ".benchmarks",     # pytest-benchmark
})


def _is_cache_dir(name: str) -> bool:
    """True for a dot-prefixed directory that holds tool state, not content.

    Two rules rather than one: a suffix test catches the `*_cache` family
    (.ruff_cache, .mypy_cache, .pyrefly_cache -- including tools not written
    yet), and an explicit set catches the ones named otherwise.
    """
    if not name.startswith("."):
        return False
    return name.endswith(CACHE_DIR_SUFFIXES) or name in CACHE_DIR_NAMES


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


def untracked_files() -> list[str]:
    """Workspace-only files, including ignored artifacts, that may be packed.

    The builder walks the working tree, not the commit, so anything lying around
    on disk ships to users. v4.169.12 carried an unfinished Android app because
    the ordinary untracked set was not checked. v4.169.43 then carried
    ``coverage.xml`` despite a clean tag because git-ignored files were omitted
    from that check under the circular assumption that every future artifact was
    already present in ``should_exclude``.

    Query ordinary and ignored files separately. The caller filters known-safe
    caches through ``should_exclude`` and refuses anything else, so adding a new
    ignore rule cannot silently expand the public release payload.
    """
    found: set[str] = set()
    queries = (
        ["git", "ls-files", "--others", "--exclude-standard"],
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
    )
    try:
        for query in queries:
            out = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
                query,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if out.returncode != 0:
                raise RuntimeError(out.stderr.strip() or "git ls-files failed")
            found.update(line.strip() for line in out.stdout.splitlines() if line.strip())
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        raise SystemExit(f"ERROR: cannot verify release workspace: {exc}") from exc
    return sorted(found)


def tracked_modes() -> dict[str, str]:
    """Return index modes by path so ZIP permissions do not depend on host OS."""
    try:
        result = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
            ["git", "ls-files", "--stage", "-z"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"ERROR: cannot read tracked release modes: {exc}") from exc
    if result.returncode != 0:
        raise SystemExit(
            "ERROR: cannot read tracked release modes: "
            + (result.stderr.strip() or "git ls-files failed")
        )

    modes: dict[str, str] = {}
    for record in result.stdout.split("\0"):
        if not record:
            continue
        try:
            metadata, path = record.split("\t", 1)
            mode = metadata.split(" ", 1)[0]
        except ValueError as exc:
            raise SystemExit(f"ERROR: malformed git index record: {record!r}") from exc
        modes[path] = mode
    if not modes:
        raise SystemExit("ERROR: tracked release mode map is empty")
    return modes


def _archive_permissions(rel_path: str, abs_path: Path, modes: dict[str, str]) -> int:
    git_mode = modes.get(rel_path)
    if git_mode is None:
        # Only reachable with the explicit --allow-untracked escape hatch.
        return 0o755 if os.access(abs_path, os.X_OK) else 0o644
    if git_mode not in SUPPORTED_GIT_FILE_MODES:
        raise SystemExit(
            f"ERROR: unsupported git mode {git_mode} for release path {rel_path}; "
            "symlinks/submodules are not valid release ZIP entries"
        )
    return 0o755 if git_mode == "100755" else 0o644


def _write_bytes_entry(archive: zipfile.ZipFile, *, rel_path: str,
                       content: bytes, permissions: int = 0o644) -> None:
    info = zipfile.ZipInfo(f"arena-bridge/{rel_path}", date_time=ZIP_TIMESTAMP)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | permissions) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(
        info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
    )


def _write_entry(
    archive: zipfile.ZipFile,
    *,
    abs_path: Path,
    rel_path: str,
    modes: dict[str, str],
) -> None:
    _write_bytes_entry(
        archive,
        rel_path=rel_path,
        content=abs_path.read_bytes(),
        permissions=_archive_permissions(rel_path, abs_path, modes),
    )


def _git_source_commit() -> str:
    result = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True, timeout=30, check=False,
    )
    commit = result.stdout.strip().lower() if result.returncode == 0 else ""
    if _COMMIT_RE.fullmatch(commit) is None:
        raise SystemExit("ERROR: cannot resolve a strict 40-hex source commit")
    return commit


def release_provenance(version: str) -> bytes:
    """Canonical source identity embedded before the archive hash exists."""
    source = (os.environ.get("ARENA_SOURCE_COMMIT")
              or os.environ.get("GITHUB_SHA") or _git_source_commit()).lower()
    run_id = (os.environ.get("ARENA_CANDIDATE_RUN_ID")
              or os.environ.get("GITHUB_RUN_ID") or "local")
    if _COMMIT_RE.fullmatch(source) is None:
        raise SystemExit("ERROR: ARENA_SOURCE_COMMIT/GITHUB_SHA must be 40 lowercase hex")
    if run_id != "local" and _RUN_RE.fullmatch(run_id) is None:
        raise SystemExit("ERROR: candidate run id must be positive decimal or local")
    value = {
        "candidateRunId": run_id,
        "releaseTag": f"v{version}",
        "repository": "IvanSkainet/arena-agent",
        "schemaVersion": 1,
        "sourceCommit": source,
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main(argv: list[str]) -> int:
    version = argv[1] if len(argv) > 1 else detect_version()
    out = Path(argv[2]) if len(argv) > 2 else Path(f"/tmp/arena-agent-v{version}.zip")

    stray = [f for f in untracked_files() if not should_exclude(f)]
    if stray and "--allow-untracked" not in argv:
        print("REFUSING: the working tree has untracked files or ignored "
              "artifacts that would be packed into the release:", file=sys.stderr)
        for name in stray[:20]:
            print(f"  {name}", file=sys.stderr)
        if len(stray) > 20:
            print(f"  ... and {len(stray) - 20} more", file=sys.stderr)
        print("\nBuild from a clean checkout of the tag, commit them, or pass "
              "--allow-untracked if this really is intended.", file=sys.stderr)
        return 1

    if out.exists():
        out.unlink()

    modes = tracked_modes()
    for rel_path, git_mode in modes.items():
        if not should_exclude(rel_path) and git_mode not in SUPPORTED_GIT_FILE_MODES:
            raise SystemExit(
                f"ERROR: unsupported git mode {git_mode} for release path {rel_path}; "
                "symlinks/submodules are not valid release ZIP entries"
            )

    entries: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        at_root = Path(dirpath) == ROOT
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in EXCLUDE_SUBDIRS and d not in EXCLUDE_EXTRA
            and not _is_cache_dir(d)
            and not (at_root and d in EXCLUDE_TOP)
        )
        for fn in filenames:
            abs_path = Path(dirpath) / fn
            rel_path = abs_path.relative_to(ROOT).as_posix()
            if not should_exclude(rel_path):
                entries.append((rel_path, abs_path))
    entries.sort(key=lambda item: item[0])

    provenance = release_provenance(version)
    file_count = 1
    total_bytes = len(provenance)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # Dot-prefixed virtual metadata sorts before every tracked entry.
        _write_bytes_entry(zf, rel_path=RELEASE_PROVENANCE, content=provenance)
        for rel_path, abs_path in entries:
            _write_entry(zf, abs_path=abs_path, rel_path=rel_path, modes=modes)
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
