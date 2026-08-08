#!/usr/bin/env python3
"""Gate: a workflow step must not be gated on a ref its workflow never sees.

A step with `if: startsWith(github.ref, 'refs/tags/v')` inside a workflow
whose only triggers are `push: branches: [master]` and `pull_request`
will never run. Not "rarely" -- never. It sits in the file looking like
protection, reports nothing, and the thing it was written to catch keeps
happening.

This is the third time the same shape has bitten in three releases:

  * v4.169.7 -- a misspelled scan directory made a gate report OK while
    reading zero files.
  * v4.169.10 (first cut) -- an anonymous 403 was swallowed as "offline"
    and the check passed blind.
  * v4.169.10 (second cut) -- the release gate was tag-gated inside a
    workflow that never runs on tags.

Every one of them was a detector that could not distinguish "nothing
wrong" from "I looked at nothing". Hence a gate for that class itself.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MIN_FILES_SCANNED = 5

TAG_CONDITION = re.compile(r"refs/tags|github\.ref_type\s*==\s*'tag'|ref_type == \"tag\"")


def _triggers_on_tags(text: str) -> bool:
    """True when the workflow can plausibly run for a tag ref."""
    head = text.split("jobs:", 1)[0]
    if "tags:" in head:
        return True
    # `on: push:` with no `branches:` filter fires for tags too.
    if re.search(r"^\s*release:", head, re.M):
        return True
    if re.search(r"^\s*workflow_dispatch:", head, re.M):
        return True
    push = re.search(r"^\s*push:\s*$(.*?)(?=^\s*\w+:\s*$|\Z)", head, re.M | re.S)
    if push and "branches" not in push.group(1):
        return True
    return False


def violations() -> tuple[list[str], int]:
    found: list[str] = []
    scanned = 0
    if not WORKFLOWS.is_dir():
        raise SystemExit(f"dead condition ratchet: workflows directory missing: {WORKFLOWS}")
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        scanned += 1
        text = path.read_text(encoding="utf-8")
        if _triggers_on_tags(text):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith(("if:", "- if:")):
                continue
            if TAG_CONDITION.search(stripped):
                found.append(
                    f"{rel}:{lineno}: step is gated on a tag ref, but this "
                    f"workflow never triggers on tags -- the step can never run"
                )
    return found, scanned


def main() -> int:
    found, scanned = violations()
    if scanned < MIN_FILES_SCANNED:
        print(f"dead condition ratchet: FAIL -- scanned only {scanned} workflow "
              f"files (expected at least {MIN_FILES_SCANNED}); the scan is broken")
        return 1
    if found:
        print("dead condition ratchet: FAIL")
        for line in found:
            print(f"  {line}")
        print()
        print("  Either add the tag trigger to the workflow, or drop the condition.")
        return 1
    print(f"dead condition ratchet: OK ({scanned} workflow files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
