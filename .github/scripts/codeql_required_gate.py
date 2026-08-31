#!/usr/bin/env python3
"""Turn GitHub's four CodeQL "Analyze (...)" checks into one blocking gate.

CodeQL runs through default setup, which cannot be listed as a required status
check by job name and is not part of any aggregate. Measured on master
f571d352: `Analyze (actions)`, `Analyze (java-kotlin)`,
`Analyze (javascript-typescript)` and `Analyze (python)` all reported, and none
of them could block a merge.

This script polls the checks on a commit and fails closed. It is deliberately
strict about the two ways a gate like this rots:

* **A missing analysis is a failure, not a pass.** If CodeQL never reported for
  a language we expect, the safe reading is "we do not know", and a gate that
  cannot tell "clean" from "never ran" is the failure mode #204 exists to stop.
* **A timeout is a failure.** Waiting forever and being killed by the job
  timeout would surface as an infrastructure error rather than a red gate.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.environ.get("GITHUB_REPOSITORY", "IvanSkainet/arena-agent")

# Languages CodeQL is configured to analyse. Kept explicit so that silently
# dropping a language from default setup turns this gate red instead of
# quietly shrinking the coverage.
EXPECTED_PREFIX = "Analyze ("
EXPECTED = (
    "Analyze (actions)",
    "Analyze (java-kotlin)",
    "Analyze (javascript-typescript)",
    "Analyze (python)",
)

# `skipped` is deliberately NOT a pass: a skipped analysis did not run, and
# "did not run" must never read as "clean" -- that is the whole point of this
# gate. Caught by Sourcery on the PR that introduced it.
PASS = {"success", "neutral"}


def _checks(sha: str) -> list[dict]:
    """Every check run reported against `sha`, via the REST API."""
    out = subprocess.run(
        ["gh", "api", "--paginate",
         f"repos/{REPO}/commits/{sha}/check-runs?per_page=100",
         "--jq", ".check_runs[] | {name,status,conclusion}"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        print(f"error: gh api failed: {out.stderr.strip()[:300]}", file=sys.stderr)
        raise SystemExit(2)
    runs = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line:
            runs.append(json.loads(line))
    return runs


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True)
    # Measured on PR #216: CodeQL default setup took over 15 minutes for
    # `Analyze (python)` and `Analyze (actions)` on a normal-sized change,
    # so the original 900s timeout failed a run whose four analyses all
    # went on to pass. 45 minutes leaves real headroom while still being a
    # bounded wait rather than an indefinite hang.
    ap.add_argument("--timeout", type=int, default=2700,
                    help="seconds to wait for CodeQL to finish")
    ap.add_argument("--poll", type=int, default=30)
    return ap.parse_args(argv)


def _analyses(sha: str) -> dict[str, dict]:
    """Just the CodeQL `Analyze (...)` checks, keyed by name."""
    return {r["name"]: r for r in _checks(sha) if r["name"].startswith(EXPECTED_PREFIX)}


def _report_timeout(pending: list[str], missing: list[str]) -> int:
    print("FAIL: timed out waiting for CodeQL.")
    if pending:
        print(f"  still running: {pending}")
    if missing:
        print(f"  never reported: {missing}")
    print("  A gate that cannot distinguish 'clean' from 'never ran'")
    print("  must fail. Check CodeQL default setup is enabled.")
    return 1


def _await_analyses(sha: str, timeout: int, poll: int) -> tuple[dict[str, dict], int | None]:
    """Poll until every expected analysis has completed.

    Returns the analyses plus an exit code, which is None while things are
    still fine and 1 once waiting has been given up on.
    """
    deadline = time.time() + timeout
    while True:
        seen = _analyses(sha)
        pending = [n for n, r in seen.items() if r["status"] != "completed"]
        missing = [n for n in EXPECTED if n not in seen]
        if not pending and not missing:
            return seen, None
        if time.time() > deadline:
            return seen, _report_timeout(pending, missing)
        print(f"waiting: pending={pending or '-'} missing={missing or '-'}")
        time.sleep(poll)


def _verdict(seen: dict[str, dict]) -> int:
    failed = [f"{n}={r['conclusion']}" for n, r in sorted(seen.items())
              if r["conclusion"] not in PASS]
    if failed:
        print(f"FAIL: CodeQL reported failures: {failed}")
        return 1
    print(f"OK: all {len(seen)} CodeQL analyses passed "
          f"({', '.join(sorted(seen))})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    seen, gave_up = _await_analyses(args.sha, args.timeout, args.poll)
    if gave_up is not None:
        return gave_up
    return _verdict(seen)


if __name__ == "__main__":
    sys.exit(main())
