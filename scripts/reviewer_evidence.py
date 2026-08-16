#!/usr/bin/env python3
"""Collect exact-head reviewer evidence from every GitHub PR surface."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.governance.reviewer_evidence import (  # noqa: E402
    EvidenceError,
    collect_github_evidence,
)


def _fetch_json(path: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "arena-reviewer-evidence",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 -- fixed GitHub API origin and validated repo path
        link = response.headers.get("Link", "")
        if 'rel="next"' in link:
            raise EvidenceError(f"GitHub response is paginated beyond the supported evidence cap: {path}")
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="IvanSkainet/arena-agent")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--expected-head")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        evidence = collect_github_evidence(
            repo=args.repo,
            pr_number=args.pr,
            fetch_json=_fetch_json,
            expected_head=args.expected_head,
        )
    except (EvidenceError, OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"reviewer evidence error: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
