"""CHANGELOG freshness guard for the bridge.

Catches the class of bug where the maintainer gets busy, no
releases ship for 60+ days, and the most recent CHANGELOG
entry stops reflecting reality. The longer the gap, the
more likely the entry is missing a security fix or a behaviour
change that the user-facing docs (or a new release) should
mention.

The guard is intentionally lenient on the *first* missing
release date (the CHANGELOG can predate this guard being
written, so we don't want to fail on day one). It only
complains if a release entry is missing an ``updated_at`` /
``captured_at`` ISO date that is more than ``--max-age-days``
old. If no dated entry is found at all, the guard exits 0
with a one-line warning (rather than blocking the build) so
the maintainer can decide.

Usage
-----

::

    python scripts/changelog_freshness.py --max-age-days 90
    python scripts/changelog_freshness.py --en CHANGELOG.md
    python scripts/changelog_freshness.py --en CHANGELOG.md --ru CHANGELOG.ru.md

Exit code:

- 0 if the most recent dated entry is within ``--max-age-days`` OR no dated entry is found
- 1 if the most recent dated entry is older than ``--max-age-days``
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple


# Match a date literal in the form we use in CHANGELOG entries:
#   "captured_at": "2026-07-24T00:00:00Z"
#   "released this / 23 Jul 20:43"  (GitHub release UI text)
#   "## v4.65.0 - ... (2026-07-24)"  (handwritten entry)
_DATE_PATTERNS = [
    # ISO 8601: 2026-07-24T00:00:00Z or 2026-07-24T00:00:00+00:00
    re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}):(\d{2})(?:Z|[+\-]\d{2}:?\d{2})?)?\b"),
]


def _extract_latest_date(text: str) -> Optional[datetime]:
    """Return the latest date literal found in ``text`` (timezone-aware UTC)."""
    candidates: List[datetime] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            hh, mm, ss = 0, 0, 0
            if m.group(4):
                hh, mm, ss = int(m.group(4)), int(m.group(5)), int(m.group(6))
            try:
                candidates.append(datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc))
            except ValueError:
                # invalid calendar date (e.g. Feb 30) — skip
                continue
    if not candidates:
        return None
    return max(candidates)


def _scan_file(path: Path, max_age_days: int) -> Tuple[str, bool]:
    """Scan a single CHANGELOG file.

    Returns (message, failed). The first element is the human-readable
    line; the second is whether the file failed (out-of-date) or
    passed (fresh / no date found).
    """
    if not path.exists():
        return f"  {path}: not found, skipping", False
    text = path.read_text(encoding="utf-8")
    latest = _extract_latest_date(text)
    if latest is None:
        return f"  {path}: no date literal found (skipped)", False
    now = datetime.now(timezone.utc)
    age = (now - latest).days
    if age > max_age_days:
        return (
            f"  {path}: latest entry is {latest.date()} (age {age}d > {max_age_days}d) — STALE",
            True,
        )
    return f"  {path}: latest entry is {latest.date()} (age {age}d <= {max_age_days}d)", False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--en", default="CHANGELOG.md", help="English CHANGELOG path")
    parser.add_argument("--ru", default="CHANGELOG.ru.md", help="Russian CHANGELOG path")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=90,
        help="Maximum age (days) of the most recent dated entry before the guard fails",
    )
    args = parser.parse_args()

    print(f"[changelog-freshness] scanning (max age {args.max_age_days}d)")
    failed = False
    for label, path in [("en", Path(args.en)), ("ru", Path(args.ru))]:
        msg, is_fail = _scan_file(path, args.max_age_days)
        print(msg)
        if is_fail:
            failed = True
    if failed:
        print(
            "[changelog-freshness] FAIL: at least one CHANGELOG is older than"
            " the threshold. Ship a release or hand-edit a dated entry."
        )
        return 1
    print("[changelog-freshness] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
