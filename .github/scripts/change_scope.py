#!/usr/bin/env python3
"""Classify a measured git diff as docs-only or full CI, failing closed."""
from __future__ import annotations

import argparse
import json
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


# The plan allows five macOS jobs at a time for the whole account, and the
# full matrix is five macOS jobs. Two runs at once already queue, and GitHub
# cancels the jobs at the back of the queue ("not acquired", #565). A pull
# request therefore runs the oldest and the newest Python on macOS; master
# runs all five, so a failure on a version in between is found on the merge
# commit, not never.
MACOS_ALL = ("3.10", "3.11", "3.12", "3.13", "3.14")
MACOS_PULL_REQUEST = (MACOS_ALL[0], MACOS_ALL[-1])


def macos_cells(event: str) -> str:
    """Return the macOS part of the test matrix for this event, as JSON."""
    versions = MACOS_PULL_REQUEST if event == "pull_request" else MACOS_ALL
    return json.dumps([{"os": "macos-latest", "python-version": version} for version in versions])


def output_lines(*, only_docs: bool, event: str) -> list[str]:
    """Return the lines the workflow reads as outputs of this job."""
    return [
        f"docs_only={'true' if only_docs else 'false'}",
        f"run_expensive={'false' if only_docs else 'true'}",
        f"macos_cells={macos_cells(event)}",
    ]


def _write_outputs(path: Path, *, only_docs: bool, event: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.writelines(line + "\n" for line in output_lines(only_docs=only_docs, event=event))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--github-output", required=True)
    parser.add_argument("--event", default="push", help="The event that started the workflow")
    args = parser.parse_args(argv)

    try:
        paths = changed_paths(args.base, args.head, repo=Path(args.repo).resolve())
        only_docs = docs_only(paths)
        _write_outputs(Path(args.github_output), only_docs=only_docs, event=args.event)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"change scope failed closed: {exc}", file=sys.stderr)
        return 1

    print("changed paths:")
    for path in paths:
        print(f"  {path}")
    print("\n".join(output_lines(only_docs=only_docs, event=args.event)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
