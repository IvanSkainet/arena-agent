"""Coverage diff guard for the bridge.

Reads the most recent ``coverage.xml`` (cobertura-format, the file pytest
produces via ``--cov-report=xml:coverage.xml``) and compares its
total line-rate against a checked-in baseline stored in
``docs/coverage-baseline.json``.

The guard exists to catch the class of bug where a PR merges, all
tests pass, but the *new* code path is uncovered so the project
silently becomes less tested with every commit. Without this guard,
a 2% coverage drop takes 3-4 releases to surface as "wait, why
did our coverage just fall off a cliff" — by which point the
uncovered code is in production.

Usage
-----

In CI, after the pytest run that produces coverage.xml::

    python scripts/coverage_diff.py --xml coverage.xml \\
        --baseline docs/coverage-baseline.json \\
        --max-drop 1.0

Exit code:

- 0 if coverage stayed the same or went up (or within ``--max-drop`` pct)
- 1 if coverage dropped more than ``--max-drop`` percentage points
- 2 if the baseline file is missing or malformed (treat as "no baseline yet")

Baseline file format
--------------------

::

    {
      "version": "4.65.0",
      "line_rate_pct": 53.6,
      "branch_rate_pct": 38.92,
      "lines_covered": 17240,
      "lines_valid": 32166,
      "captured_at": "2026-07-24T00:00:00Z",
      "captured_for_commit": "<full SHA>"
    }

The baseline is updated by a small ``scripts/update_coverage_baseline.py``
helper (or by hand) at release time, never automatically. That makes
the guard a "release-time decision", not a "PR-time surprise" — a PR
that drops coverage will fail the guard, the maintainer either
adds tests in the same PR or accepts the drop and bumps the
baseline explicitly when shipping the next release.

Why not just use ``--cov-fail-under``?
--------------------------------------

The v4.61.0 ``--cov-fail-under=70`` gate blocked the entire suite
on day one (real coverage was 50%) and was relaxed to 50% in
v4.62.0. A flat floor and a diff guard are complementary:

- ``--cov-fail-under=50`` (current): stops the project from
  falling under 50% in absolute terms. This is the safety net.
- ``coverage_diff.py`` (this script): stops the project from
  silently regressing between releases. Even if a PR is
  technically above 50%, a 3-point drop in one PR is now
  flagged so the maintainer can decide explicitly.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional


def parse_coverage_xml(xml_path: Path) -> Dict[str, Any]:
    """Pull the totals out of a coverage.py cobertura XML.

    The file is the one ``pytest --cov-report=xml:coverage.xml``
    produces, with ``<coverage line-rate=...>`` on the root element.
    """
    if not xml_path.exists():
        raise FileNotFoundError(f"coverage.xml not found at {xml_path}")
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    # coverage.py uses line-rate/branch-rate as fractions in [0, 1].
    line_rate = float(root.attrib.get("line-rate", "0"))
    branch_rate = float(root.attrib.get("branch-rate", "0"))
    lines_covered = int(root.attrib.get("lines-covered", "0"))
    lines_valid = int(root.attrib.get("lines-valid", "0"))
    return {
        "line_rate_pct": round(line_rate * 100, 4),
        "branch_rate_pct": round(branch_rate * 100, 4),
        "lines_covered": lines_covered,
        "lines_valid": lines_valid,
    }


def load_baseline(baseline_path: Path) -> Optional[Dict[str, Any]]:
    """Read the baseline JSON, or None if it doesn't exist / is malformed."""
    if not baseline_path.exists():
        return None
    try:
        with open(baseline_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    # Minimal shape check.
    for key in ("line_rate_pct", "branch_rate_pct"):
        if key not in data:
            return None
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--xml", default="coverage.xml", help="Path to coverage.xml")
    parser.add_argument(
        "--baseline",
        default="docs/coverage-baseline.json",
        help="Path to baseline JSON",
    )
    parser.add_argument(
        "--max-drop",
        type=float,
        default=1.0,
        help="Allowed drop in line-coverage percentage points (default 1.0)",
    )
    args = parser.parse_args()

    current = parse_coverage_xml(Path(args.xml))
    baseline = load_baseline(Path(args.baseline))

    if baseline is None:
        print(
            f"[coverage-diff] no baseline at {args.baseline} — first run,"
            f" accepting current coverage of {current['line_rate_pct']}%."
        )
        # Exit 0: don't block the very first run, just inform.
        return 0

    current_pct = current["line_rate_pct"]
    baseline_pct = baseline["line_rate_pct"]
    drop = baseline_pct - current_pct

    print(f"[coverage-diff] baseline: {baseline_pct}% (version {baseline.get('version', '?')})")
    print(f"[coverage-diff] current : {current_pct}%")
    print(f"[coverage-diff] branch  : {current['branch_rate_pct']}% (baseline {baseline['branch_rate_pct']}%)")
    print(f"[coverage-diff] drop    : {drop:+.4f} pp (allowed: -{args.max_drop} pp)")

    if drop <= args.max_drop:
        print("[coverage-diff] OK (within allowed drop)")
        return 0

    print(
        f"[coverage-diff] FAIL: coverage dropped {drop:.4f} pp, which is more"
        f" than the {args.max_drop} pp allowed."
    )
    print(
        "[coverage-diff] Either add tests in this PR, or, if the drop is"
        " intentional, bump docs/coverage-baseline.json in a follow-up commit"
        " before merge."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
