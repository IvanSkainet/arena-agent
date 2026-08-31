#!/usr/bin/env python3
"""Bandit half of the security gate: HIGH/MEDIUM zero-tolerance + LOW ratchet.

Split out of `security_gate.py` because CodeScene flagged that file for
Overall Code Complexity once the LOW ratchet landed in it. The bandit rules
are self-contained, so they live here and `security_gate.py` re-exports
`check_bandit` for its CLI.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    """Read a scanner report, failing loudly on anything unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"error: report not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except json.JSONDecodeError as exc:
        print(f"error: report is not valid JSON: {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(data, dict):
        print(f"error: report must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def _bandit_low_ceiling() -> int:
    """The agreed LOW-severity ceiling, read from a checked-in file.

    LOW findings are real signal that was never being counted: 496 of them,
    250 of which are B110 try_except_pass -- silently swallowed exceptions,
    the exact fail-open shape this repo keeps getting bitten by. Fixing all
    496 at once is not realistic, so this is a ratchet: the number may fall,
    never rise.
    """
    ceiling = ROOT / "docs" / "bandit-low-ceiling.txt"
    if not ceiling.exists():
        print(f"error: {ceiling} is missing; the LOW ratchet cannot be evaluated. "
              f"A gate that cannot find its baseline must fail, not pass.",
              file=sys.stderr)
        raise SystemExit(2)
    try:
        return int(ceiling.read_text(encoding="utf-8").split("#")[0].strip())
    except ValueError as exc:
        print(f"error: {ceiling} is malformed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _validate_bandit_results(results: object) -> int | None:
    """Reject a malformed report. Returns an exit code, or None if valid.

    Callers must narrow `results` themselves afterwards; see `_as_findings`.
    """
    if not isinstance(results, list):
        print("error: bandit report must contain a results array", file=sys.stderr)
        return 2
    for item in results:
        if not isinstance(item, dict):
            print("error: bandit result must be an object", file=sys.stderr)
            return 2
        if (
            not isinstance(item.get("issue_severity"), str)
            or not isinstance(item.get("test_id"), str)
        ):
            print("error: bandit result has missing/invalid required fields", file=sys.stderr)
            return 2
    return None


def _as_findings(results: object) -> list[dict]:
    """Narrow an already-validated results payload for the type checker.

    `_validate_bandit_results` has proved the shape at runtime, but that fact
    does not survive into the checker, which then flags the payload as
    non-iterable. This makes the narrowing explicit rather than silencing it.
    """
    assert isinstance(results, list)
    return results


def _report_fatal(results: list[dict], fatal: int) -> int:
    print(f"FAIL: bandit found {fatal} HIGH/MEDIUM findings")
    for r in results:
        if r.get("issue_severity") in ("HIGH", "MEDIUM"):
            print(f"  {r.get('filename')}:{r.get('line_number')} "
                  f"[{r.get('test_id')}] {r.get('issue_text', '')[:100]}")
    return 1


def _report_low_regression(results: list[dict], low: int, ceiling: int) -> int:
    print(f"FAIL: bandit LOW findings rose to {low}, ceiling is {ceiling}.")
    print("  LOW is capped by a ratchet. Fix the new finding, or -- if it is")
    print("  genuinely unavoidable -- raise docs/bandit-low-ceiling.txt in the")
    print("  same PR with a written justification.")
    by_test: dict[str, int] = {}
    for r in results:
        if r.get("issue_severity") == "LOW":
            tid = f"{r.get('test_id')} {r.get('issue_text', '')[:40]}"
            by_test[tid] = by_test.get(tid, 0) + 1
    for tid, n in sorted(by_test.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {n:4d}  {tid}")
    return 1


def _count_by_severity(results: list[dict]) -> dict[str, int]:
    by_sev: dict[str, int] = {}
    for r in results:
        sev = r.get("issue_severity", "?")
        by_sev[sev] = by_sev.get(sev, 0) + 1
    return by_sev


def _report_low_ok(low: int, ceiling: int) -> int:
    if low < ceiling:
        print(f"OK: bandit LOW at {low}, below the ceiling of {ceiling}. "
              f"Lower docs/bandit-low-ceiling.txt to {low} to lock the gain in.")
    else:
        print(f"OK: bandit LOW at the ceiling ({ceiling})")
    print("OK: bandit clean at HIGH+MEDIUM")
    return 0


def check_bandit(report_path: str) -> int:
    """Fail on any HIGH or MEDIUM finding, and ratchet LOW downward."""
    raw = _load(report_path).get("results")
    invalid = _validate_bandit_results(raw)
    if invalid is not None:
        return invalid
    results = _as_findings(raw)

    by_sev = _count_by_severity(results)
    print(f"bandit findings by severity: {by_sev}")

    # Validate the ratchet baseline BEFORE the fatal-severity return: a missing
    # or malformed ceiling means "this gate is broken" (rc=2), and that must
    # not be masked by an ordinary finding failure.
    ceiling = _bandit_low_ceiling()

    fatal = by_sev.get("HIGH", 0) + by_sev.get("MEDIUM", 0)
    if fatal:
        return _report_fatal(results, fatal)

    low = by_sev.get("LOW", 0)
    if low > ceiling:
        return _report_low_regression(results, low, ceiling)
    return _report_low_ok(low, ceiling)
