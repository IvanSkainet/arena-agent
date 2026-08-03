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
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "quality_baseline.json"
# scripts/ and bin/ ship inside the release zip and are executed by the user,
# so they are checked like the package itself (v4.157.0, after clearing 67
# findings there). vulture stays on `arena` only: the CLI entry points are
# invoked by name from shells and skills, which it cannot see.
PYREFLY_TARGETS = ("arena", "scripts", "bin")


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


def pyrefly_errors() -> list[dict]:
    # rc 0 = clean, 1 = errors found
    proc = run([sys.executable, "-m", "pyrefly", "check", *PYREFLY_TARGETS,
                "--output-format=json"], {0, 1})
    return json.loads(proc.stdout or "{}").get("errors", [])


def pyrefly_counts(errors: list[dict]) -> Counter:
    counts: Counter = Counter()
    for err in errors:
        counts[err.get("name") or "unknown"] += 1
    return counts


def collect() -> tuple[dict, list[dict]]:
    errors = pyrefly_errors()
    pf = pyrefly_counts(errors)
    return ({
        "vulture": {"TOTAL": vulture_count()},
        "pyrefly": {**dict(sorted(pf.items())), "TOTAL": sum(pf.values())},
    }, errors)


def _write_step_summary(lines: list[str]) -> None:
    """Append a markdown summary for the GitHub Actions job page when the
    ``GITHUB_STEP_SUMMARY`` path is present (no-op locally)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    current, errors = collect()
    # Debt-visibility mode: fails while ANY vulture/pyrefly findings remain.
    # The blocking ratchet gates GROWTH; this non-blocking mode owns the red
    # X for the residual volume so it is visible at the checkmark level
    # rather than buried in green job logs. Red by design until zero.
    if "--fail-on-any" in sys.argv[1:]:
        totals = {t: current[t]["TOTAL"] for t in ("vulture", "pyrefly")}
        grand = sum(totals.values())
        lines = ["## Quality debt (visibility, non-blocking)", ""]
        if grand:
            lines.append(f"**Total: {grand} findings** "
                         f"(vulture={totals['vulture']}, "
                         f"pyrefly={totals['pyrefly']}).")
            lines.append("")
            lines.append("| Kind | Count |")
            lines.append("|---|---|")
            for kind, n in sorted(current["pyrefly"].items()):
                if kind != "TOTAL" and n:
                    lines.append(f"| pyrefly/{kind} | {n} |")
            if totals["vulture"]:
                lines.append(f"| vulture/TOTAL | {totals['vulture']} |")
            _write_step_summary(lines)
            print(f"QUALITY DEBT PRESENT: vulture={totals['vulture']} "
                  f"pyrefly={totals['pyrefly']} (visibility gate, red by "
                  f"design until zero)")
            for kind, n in sorted(current["pyrefly"].items()):
                if kind != "TOTAL" and n:
                    print(f"  pyrefly/{kind}: {n}")
            return 1
        lines.append("**Total: 0 — no quality debt.**")
        _write_step_summary(lines)
        print("QUALITY DEBT ZERO.")
        return 0
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
                growth.append((f"  {tool}/{kind}: {was} -> {now} (+{now - was})",
                               kind if tool == "pyrefly" else None))
    if growth:
        print("QUALITY DEBT GREW (ratchet blocks this):")
        print("\n".join(g[0] for g in growth))
        # full details of grown-kinds errors — a gate that fails must say
        # exactly WHAT it found, or nobody can reproduce/fix it
        grown_kinds = {g[1] for g in growth if g[1]}
        if grown_kinds:
            print("\nDetails:")
            for err in errors:
                if (err.get("name") or "unknown") in grown_kinds:
                    print(f"  {err.get('path')}:{err.get('line')} "
                          f"[{err.get('name')}] "
                          f"{(err.get('message') or '').strip()[:200]}")
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
