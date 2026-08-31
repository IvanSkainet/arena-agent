"""Per-test-id ceilings for the bandit LOW ratchet.

Kept out of ``bandit_gate.py`` deliberately: that file already carries the
severity gate, and CodeScene flagged Overall Code Complexity when this
logic lived alongside it.

A single total was gameable. 496 findings stayed 496 whether they were
496 subprocess imports or 466 imports plus 30 new silent
``except Exception: pass`` blocks, so a real regression could be paid for
by deleting unrelated findings. Each test id now ratchets on its own.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any


def _load_ceilings_file(path: pathlib.Path) -> dict[str, Any]:
    """Read the checked-in baseline, failing closed (rc=2) if unusable.

    A gate that cannot read its own baseline does not know whether the code
    is clean, and "I do not know" must never be reported as a pass.
    """
    if not path.exists():
        print(f"error: {path} is missing; the per-test ratchet cannot run.",
              file=sys.stderr)
        raise SystemExit(2)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: {path} is malformed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(data, dict):
        print(f"error: {path} must be a JSON object", file=sys.stderr)
        raise SystemExit(2)
    return data


def per_test_ceilings(root: pathlib.Path) -> dict[str, int]:
    """Map bandit test id -> allowed LOW count. Keys starting with _ are notes."""
    path = root / "docs" / "bandit-low-ceilings.json"
    raw = _load_ceilings_file(path)
    ceilings = {k: v for k, v in raw.items() if not k.startswith("_")}
    if not ceilings or not all(isinstance(v, int) for v in ceilings.values()):
        print(f"error: {path} must map test ids to integers", file=sys.stderr)
        raise SystemExit(2)
    return ceilings


def low_counts_by_test(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        if item.get("issue_severity") == "LOW":
            tid = str(item.get("test_id"))
            counts[tid] = counts.get(tid, 0) + 1
    return counts


def _report_risen(risen: list[tuple[str, int, int]]) -> None:
    print("\nFAIL: these bandit tests rose above their ceilings:")
    for tid, found, cap in risen:
        print(f"    {tid}: {found} > {cap}")
    print("  Fix the new findings, or raise that entry in")
    print("  docs/bandit-low-ceilings.json with a written justification.")


def _report_fallen(fallen: list[tuple[str, int, int]]) -> None:
    for tid, found, cap in fallen:
        print(f"    {tid} improved: {found} < {cap} -- lower it in "
              f"docs/bandit-low-ceilings.json to lock the gain in")


def check_per_test(results: list[dict], root: pathlib.Path) -> int:
    """Return 1 if any test id exceeds its own ceiling, else 0."""
    ceilings = per_test_ceilings(root)
    counts = low_counts_by_test(results)
    risen = [(t, counts.get(t, 0), c) for t, c in ceilings.items()
             if counts.get(t, 0) > c]
    new = [(t, n, 0) for t, n in counts.items() if t not in ceilings and n > 0]
    fallen = [(t, counts.get(t, 0), c) for t, c in ceilings.items()
              if counts.get(t, 0) < c]
    if risen or new:
        _report_risen(risen + new)
        return 1
    if fallen:
        _report_fallen(fallen)
    return 0
