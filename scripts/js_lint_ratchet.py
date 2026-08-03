#!/usr/bin/env python3
"""Debt ratchet for the JavaScript surface (oxlint).

Until v4.157.0 the 17k lines under ``dashboard/assets`` and
``chat_extension`` were linted by nothing at all: semgrep runs on ``arena/``
only, and CodeQL is a SAST engine, not a linter -- it does not report
``no-func-assign`` or a body on a GET request. The first run found a real
defect (fetch() with a body on the default GET, which throws TypeError at
runtime in the service worker).

This mirrors scripts/lint_ratchet.py: the residual volume is tolerated, but
GROWTH is blocked. Fail closed -- a missing/broken oxlint aborts loudly
instead of reporting "zero debt".

    python scripts/js_lint_ratchet.py                  # gate check
    python scripts/js_lint_ratchet.py --fail-on-any    # visibility mode
    python scripts/js_lint_ratchet.py --write-baseline # after cleanups
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "js_lint_baseline.json"
TARGETS = ("dashboard/assets", "chat_extension")


def _oxlint_bin() -> str:
    for candidate in ("oxlint", str(ROOT / "node_modules" / ".bin" / "oxlint")):
        found = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if found:
            return found
    print("FAIL-CLOSED: oxlint not found on PATH or in node_modules/.bin",
          file=sys.stderr)
    raise SystemExit(2)


def collect() -> Counter:
    proc = subprocess.run(
        [_oxlint_bin(), "-c", ".oxlintrc.json", "--format=json", *TARGETS],
        cwd=ROOT, capture_output=True, text=True,
    )
    # oxlint exits 1 when it reports findings; anything else is a real failure.
    if proc.returncode not in (0, 1):
        print(f"FAIL-CLOSED: oxlint exited {proc.returncode}\n{proc.stderr[-800:]}",
              file=sys.stderr)
        raise SystemExit(2)
    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        print(f"FAIL-CLOSED: oxlint output is not JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    diagnostics = payload if isinstance(payload, list) else payload.get("diagnostics", [])
    counts: Counter = Counter()
    for item in diagnostics:
        counts[item.get("code") or "unknown"] += 1
    return counts


def _write_step_summary(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    current = collect()
    total = sum(current.values())

    if "--write-baseline" in sys.argv:
        BASELINE.write_text(
            json.dumps({**dict(sorted(current.items())), "TOTAL": total}, indent=2) + "\n",
            encoding="utf-8")
        print(f"js lint baseline written: {total} findings -> {BASELINE}")
        return 0

    try:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"FAIL-CLOSED: missing {BASELINE}; run --write-baseline first",
              file=sys.stderr)
        return 2
    baseline.pop("TOTAL", None)

    if "--fail-on-any" in sys.argv:
        if total:
            print(f"JS LINT DEBT PRESENT: {total} findings "
                  "(visibility gate, red by design until zero)")
            for rule, n in current.most_common():
                print(f"  {rule}: {n}")
            _write_step_summary([f"### JS lint debt: {total}"])
            return 1
        print("JS LINT DEBT ZERO.")
        return 0

    grown = {rule: (baseline.get(rule, 0), n)
             for rule, n in current.items() if n > baseline.get(rule, 0)}
    if grown:
        print("JS LINT DEBT GREW (ratchet blocks this):")
        for rule, (was, now) in sorted(grown.items()):
            print(f"  {rule}: {was} -> {now} (+{now - was})")
        print("\nFix the new findings, or lower the floor after cleanup: "
              "python scripts/js_lint_ratchet.py --write-baseline")
        return 1

    shrunk = {r: (baseline[r], current.get(r, 0))
              for r in baseline if current.get(r, 0) < baseline[r]}
    if shrunk:
        print("JS lint debt shrank (lower the baseline to lock it in):")
        for rule, (was, now) in sorted(shrunk.items()):
            print(f"  {rule}: {was} -> {now}")
    print(f"OK: {total} findings, none above the recorded floor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
