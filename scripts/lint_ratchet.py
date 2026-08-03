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
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "lint_baseline.json"
# v4.157.0: the gate covers the WHOLE tree. It grew in two steps -- first
# scripts/ and bin/ (433 findings; they are shipped by make_release_zip.py, so
# the user executes them), then the last stragglers outside any package:
# unified_bridge.py itself, _arena_helper.py, skills/*/run.py and dev/. A
# scope that excludes the main entry point is not a gate, it is a preference.
# "." rather than a list: a new top-level file is then inside the gate by
# default instead of silently outside it.
TARGETS = (".",)


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


def _write_step_summary(lines: list[str]) -> None:
    """Append a markdown summary for the GitHub Actions job page when the
    ``GITHUB_STEP_SUMMARY`` path is present (no-op locally)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    counts = current_counts()
    # Debt-visibility mode: the ratchet gates GROWTH; this mode exists for
    # the non-blocking debt job and fails while ANY debt remains, so the
    # residual legacy volume owns a red X instead of hiding behind the
    # green growth-gate. Exit 1 intentionally until counts reach zero.
    if "--fail-on-any" in sys.argv[1:]:
        total = sum(counts.values())
        lines = ["## Ruff lint debt (visibility, non-blocking)", ""]
        if total:
            lines.append(f"**Total: {total} violations across "
                         f"{len(counts)} rules.**")
            lines.append("")
            lines.append("| Rule | Count |")
            lines.append("|---|---|")
            lines += [f"| {r} | {n} |" for r, n in counts.most_common()]
            _write_step_summary(lines)
            print(f"LINT DEBT PRESENT: {total} violations "
                  f"across {len(counts)} rules (visibility gate, red by "
                  f"design until zero):")
            for rule, n in counts.most_common():
                print(f"  {rule}: {n}")
            return 1
        lines.append("**Total: 0 — no lint debt.**")
        _write_step_summary(lines)
        print("LINT DEBT ZERO.")
        return 0
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
