#!/usr/bin/env python3
"""Run mutation testing over a set of files and write a readable report.

The operator asked for a one-off sweep whose result survives the chat and
does not get cancelled by the next commit. Both are handled outside this
script -- `.github/workflows/mutation-sweep.yml` is `workflow_dispatch`
only, sits in its own concurrency group with `cancel-in-progress: false`,
and uploads the report as an artifact.

What this script adds is picking targets honestly.

**Only files the suite actually executes are worth mutating.** Measured
during the v4.163.0 cycle: `arena/mobile/mirror.py` produced 180 mutants
and killed zero, not because the tests were weak but because coverage
reported "No data to report" for that file -- nothing ran it. A survivor
count on unexecuted code is not a weak signal, it is no signal, and it
costs the same CPU hours as a real one. So targets are filtered by
coverage before anything is mutated.

**Results are cached by content.** `scripts/mutation_cache.py` keys on
(source, its tests, mutmut version), so a re-run after an unrelated
change re-proves only what changed. Measured: 146s cold, 0s cached.

Usage:
    python scripts/mutation_sweep.py                    # gate TARGETS
    python scripts/mutation_sweep.py --paths a.py,b.py
    python scripts/mutation_sweep.py --min-coverage 50
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mutation_cache  # noqa: E402
from mutation_gate import TARGETS  # noqa: E402

CACHE = ROOT / ".mutmut-cache"


def _coverage_map() -> dict[str, float]:
    """percent-covered per file, or {} if no coverage data is available."""
    report = ROOT / ".cov.json"
    if not report.exists():
        return {}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {name: meta["summary"]["percent_covered"]
            for name, meta in data.get("files", {}).items()}


def _run_one(source: str, tests: tuple[str, ...], *,
             timeout: int) -> dict[str, int | str]:
    existing = [t for t in tests if (ROOT / t).exists()]
    if not existing:
        return {"error": "no guarding tests exist"}

    CACHE.unlink(missing_ok=True)
    runner = ("python3 -m pytest -x -q --no-cov -p no:randomly "
              + " ".join(existing))
    started = time.time()
    proc = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
        ["mutmut", "run", "--paths-to-mutate", source,
         "--runner", runner, "--no-progress"],
        cwd=ROOT, capture_output=True, text=True, timeout=timeout,
    )
    elapsed = int(time.time() - started)

    if not CACHE.exists():
        tail = ((proc.stdout or "")[-400:] + (proc.stderr or "")[-400:])
        return {"error": f"mutmut produced no cache; tail: {tail}"}

    con = sqlite3.connect(CACHE)
    try:
        counts = dict(con.execute(
            "select status, count(*) from Mutant group by status").fetchall())
    finally:
        con.close()

    survived = int(counts.get("bad_survived", 0))
    killed = int(counts.get("ok_killed", 0))
    total = sum(int(v) for v in counts.values())
    result: dict[str, int | str] = {
        "survived": survived, "killed": killed,
        "total": total, "seconds": elapsed,
    }
    if total and killed == 0:
        # The mirror.py lesson: all-survived means the tests never ran the
        # file, which is a coverage fact dressed up as a mutation score.
        result["warning"] = (
            "nothing was killed -- the listed tests probably do not "
            "execute this file, so the count is meaningless rather than "
            "alarming")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", default="",
                        help="comma-separated sources (default: gate TARGETS)")
    parser.add_argument("--min-coverage", type=float, default=50.0,
                        help="skip files below this %% coverage")
    parser.add_argument("--per-file-timeout", type=int, default=3600)
    parser.add_argument("--report", default="mutation-report.md")
    parser.add_argument("--json", dest="json_out", default="mutation-report.json")
    args = parser.parse_args()

    if shutil.which("mutmut") is None:
        print("SKIP: mutmut is not installed (pip install mutmut==2.5.1)")
        return 0

    if args.paths.strip():
        targets = {p.strip(): TARGETS.get(p.strip(), ())
                   for p in args.paths.split(",") if p.strip()}
    else:
        targets = dict(TARGETS)

    coverage = _coverage_map()
    rows: list[dict] = []
    for source, tests in sorted(targets.items()):
        if not (ROOT / source).exists():
            rows.append({"source": source, "status": "missing"})
            continue
        covered = coverage.get(source)
        if covered is not None and covered < args.min_coverage:
            rows.append({"source": source, "status": "skipped-low-coverage",
                         "coverage": round(covered, 1)})
            continue
        if not tests:
            rows.append({"source": source, "status": "no-tests-declared"})
            continue

        cached = mutation_cache.lookup(source, tests)
        if cached is not None:
            rows.append({"source": source, "status": "cached",
                         "survived": cached["survived"],
                         "total": cached["total"]})
            continue

        outcome = _run_one(source, tests, timeout=args.per_file_timeout)
        if "error" in outcome:
            rows.append({"source": source, "status": "error",
                         "detail": outcome["error"]})
            continue
        mutation_cache.record(source, tests,
                              survived=int(outcome["survived"]),
                              total=int(outcome["total"]),
                              reason="sweep")
        rows.append({"source": source, "status": "ran", **outcome})

    lines = ["# Mutation sweep", ""]
    lines.append("| file | status | survived | total | seconds |")
    lines.append("|---|---|---:|---:|---:|")
    for row in rows:
        lines.append(
            f"| `{row['source']}` | {row['status']} | "
            f"{row.get('survived', '')} | {row.get('total', '')} | "
            f"{row.get('seconds', '')} |")
    warned = [r for r in rows if r.get("warning")]
    if warned:
        lines += ["", "## Warnings", ""]
        for row in warned:
            lines.append(f"* `{row['source']}`: {row['warning']}")
    errored = [r for r in rows if r["status"] == "error"]
    if errored:
        lines += ["", "## Errors", ""]
        for row in errored:
            lines.append(f"* `{row['source']}`: {row['detail']}")

    Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(args.json_out).write_text(json.dumps(rows, indent=1) + "\n",
                                   encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
