#!/usr/bin/env python3
"""Classify a measured git diff as docs-only or full CI, failing closed."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_SHA = re.compile(r"[0-9a-fA-F]{40}")
_DOC_PREFIXES = ("docs/", ".github/ISSUE_TEMPLATE/")
_DOC_FILES = frozenset({".github/pull_request_template.md"})
_DOC_SUFFIXES = frozenset({".md", ".mdx", ".rst"})


def _normalize(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./").strip()


def is_docs_path(path: str) -> bool:
    normalized = _normalize(path)
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return False
    if normalized in _DOC_FILES or normalized.startswith(_DOC_PREFIXES):
        return True
    return Path(normalized).suffix.lower() in _DOC_SUFFIXES


def docs_only(paths: list[str]) -> bool:
    """Empty or unclassifiable input runs full CI rather than guessing."""
    normalized = [_normalize(path) for path in paths if _normalize(path)]
    return bool(normalized) and all(is_docs_path(path) for path in normalized)


def changed_paths(base: str, head: str, *, repo: Path) -> list[str]:
    if not _SHA.fullmatch(base) or not _SHA.fullmatch(head):
        raise ValueError("base and head must be full 40-character commit SHAs")
    if set(base) == {"0"} or set(head) == {"0"}:
        return []
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            base,
            head,
            "--",
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr.strip()}")
    return [_normalize(line) for line in result.stdout.splitlines() if _normalize(line)]


def _write_outputs(path: Path, *, only_docs: bool) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"docs_only={'true' if only_docs else 'false'}\n")
        stream.write(f"run_expensive={'false' if only_docs else 'true'}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--github-output", required=True)
    args = parser.parse_args(argv)

    try:
        paths = changed_paths(args.base, args.head, repo=Path(args.repo).resolve())
        only_docs = docs_only(paths)
        _write_outputs(Path(args.github_output), only_docs=only_docs)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"change scope failed closed: {exc}", file=sys.stderr)
        return 1

    print("changed paths:")
    for path in paths:
        print(f"  {path}")
    print(f"docs_only={'true' if only_docs else 'false'}")
    print(f"run_expensive={'false' if only_docs else 'true'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
