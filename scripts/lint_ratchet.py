#!/usr/bin/env python3
"""Ruff violation-count ratchet.

Philosophy: the legacy codebase carries a known lint debt. We do not
gate CI on the absolute number (it would be red forever), but we DO
gate on *growth*: no commit may increase the per-rule violation counts
recorded in ``scripts/lint_baseline.json``. Cleanups lower counts; the
maintainer then regenerates the baseline in the same commit so the
floor keeps dropping:

    python scripts/lint_ratchet.py --write-baseline

Exit codes: 0 = at or below baseline, 1 = growth detected.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "lint_baseline.json"
TARGETS = ("arena", "tests")


def current_counts() -> Counter:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *TARGETS,
         "--output-format=json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    # Fail CLOSED: rc 0 = clean, 1 = violations found, anything else
    # (usage error, bad config) must abort, never report "zero debt".
    if proc.returncode not in (0, 1):
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(2)
    counts: Counter = Counter()
    for item in json.loads(proc.stdout or "[]"):
        counts[item.get("code") or "UNKNOWN"] += 1
    return counts


def main() -> int:
    counts = current_counts()
    if "--write-baseline" in sys.argv[1:]:
        BASELINE.write_text(
            json.dumps(dict(sorted(counts.items())), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"baseline written: {sum(counts.values())} violations "
              f"across {len(counts)} rules -> {BASELINE.relative_to(ROOT)}")
        return 0

    baseline = Counter(json.loads(BASELINE.read_text(encoding="utf-8")))
    growth = {r: (baseline.get(r, 0), counts[r])
              for r in counts if counts[r] > baseline.get(r, 0)}
    reduced = sum(baseline.values()) - sum(counts.values())

    if growth:
        print("LINT DEBT GREW (ratchet blocks this):")
        for rule, (was, now) in sorted(growth.items()):
            print(f"  {rule}: {was} -> {now} (+{now - was})")
        print("\nFix the new violations, or if this is deliberate hygiene,"
              " regenerate the floor: python scripts/lint_ratchet.py"
              " --write-baseline")
        return 1

    print(f"OK: {sum(counts.values())} violations at/below baseline "
          f"({sum(baseline.values())}).")
    if reduced > 0:
        print(f"NOTE: debt shrank by {reduced}. Regenerate baseline in the"
              f" same commit: python scripts/lint_ratchet.py --write-baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
