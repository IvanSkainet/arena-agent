#!/usr/bin/env python3
"""Quality debt ratchet for vulture (dead code) and pyrefly (type errors).

Pattern mirrors scripts/lint_ratchet.py: the absolute legacy volume is
tolerated for now, but GROWTH is blocked in CI. Per-kind pyrefly counts
prevent fixing 50 attribute errors while adding 50 bad assignments.

    python scripts/quality_ratchet.py                  # gate check
    python scripts/quality_ratchet.py --write-baseline # after cleanups

Fail closed: any tool/config error aborts loudly instead of reporting
"zero debt".
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "quality_baseline.json"


def run(cmd: list[str], ok_rc: set[int]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode not in ok_rc:
        print(f"FAIL-CLOSED: {' '.join(cmd)} exited {proc.returncode}\n"
              f"{proc.stderr[-800:]}", file=sys.stderr)
        raise SystemExit(2)
    return proc


def vulture_count() -> int:
    # rc 0 = clean, 3 = dead code found
    proc = run([sys.executable, "-m", "vulture", "arena",
                "--min-confidence", "80"], {0, 3})
    return sum(1 for ln in proc.stdout.splitlines() if ": (" in ln)


def pyrefly_counts() -> Counter:
    # rc 0 = clean, 1 = errors found
    proc = run([sys.executable, "-m", "pyrefly", "check", "arena",
                "--output-format=json"], {0, 1})
    counts: Counter = Counter()
    for err in json.loads(proc.stdout or "{}").get("errors", []):
        counts[err.get("name") or "unknown"] += 1
    return counts


def collect() -> dict:
    pf = pyrefly_counts()
    return {
        "vulture": {"TOTAL": vulture_count()},
        "pyrefly": {**dict(sorted(pf.items())), "TOTAL": sum(pf.values())},
    }


def main() -> int:
    current = collect()
    if "--write-baseline" in sys.argv[1:]:
        BASELINE.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(f"quality baseline written: vulture={current['vulture']['TOTAL']}"
              f" pyrefly={current['pyrefly']['TOTAL']} -> {BASELINE.relative_to(ROOT)}")
        return 0

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    growth = []
    for tool in ("vulture", "pyrefly"):
        for kind, now in current[tool].items():
            was = baseline[tool].get(kind, 0)
            if now > was:
                growth.append(f"  {tool}/{kind}: {was} -> {now} (+{now - was})")
    if growth:
        print("QUALITY DEBT GREW (ratchet blocks this):")
        print("\n".join(growth))
        print("\nFix the new findings, or lower the floor after cleanup:"
              " python scripts/quality_ratchet.py --write-baseline")
        return 1

    shrunk = (baseline["vulture"]["TOTAL"] - current["vulture"]["TOTAL"],
              baseline["pyrefly"]["TOTAL"] - current["pyrefly"]["TOTAL"])
    print(f"OK: vulture={current['vulture']['TOTAL']}, "
          f"pyrefly={current['pyrefly']['TOTAL']} at/below baseline "
          f"({baseline['vulture']['TOTAL']}/{baseline['pyrefly']['TOTAL']})")
    if shrunk != (0, 0):
        print(f"NOTE: debt shrank by vulture={shrunk[0]} pyrefly={shrunk[1]};"
              " regenerate the floor in the same commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
