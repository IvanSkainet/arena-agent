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


def _read_json_baseline(path: pathlib.Path, what: str) -> dict[str, object]:
    """Load a checked-in baseline file, failing closed if it cannot be read.

    A gate that cannot find or parse its own baseline does not know whether
    the code is clean, and "I do not know" must never be reported as a pass.
    """
    if not path.exists():
        print(f"error: {path} is missing; the {what} cannot be evaluated.",
              file=sys.stderr)
        raise SystemExit(2)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: {path} is malformed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(data, dict):
        print(f"error: {path} must be a JSON object", file=sys.stderr)
        raise SystemExit(2)
    return data


def _per_test_ceilings() -> dict[str, int]:
    """Per-test-id LOW ceilings, read from a checked-in file.

    A single total was gameable: 30 new try_except_pass could hide under the
    cap by deleting 30 subprocess imports elsewhere. Each test id now
    ratchets on its own.
    """
    path = ROOT / "docs" / "bandit-low-ceilings.json"
    raw = _read_json_baseline(path, "per-test ratchet")
    ceilings = {k: v for k, v in raw.items() if not k.startswith("_")}
    if not ceilings or not all(isinstance(v, int) for v in ceilings.values()):
        print(f"error: {path} must map test ids to integers", file=sys.stderr)
        raise SystemExit(2)
    return ceilings


def _low_counts_by_test(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        if r.get("issue_severity") == "LOW":
            tid = str(r.get("test_id"))
            counts[tid] = counts.get(tid, 0) + 1
    return counts


def _report_risen(risen: list[tuple[str, int, int]]) -> int:
    print("\nFAIL: these bandit tests rose above their ceilings:")
    for tid, found, cap in risen:
        print(f"    {tid}: {found} > {cap}")
    print("  Fix the new findings, or raise that entry in")
    print("  docs/bandit-low-ceilings.json with a written justification.")
    return 1


def _report_fallen(fallen: list[tuple[str, int, int]]) -> None:
    for tid, found, cap in fallen:
        print(f"    {tid} improved: {found} < {cap} -- lower it in "
              f"docs/bandit-low-ceilings.json to lock the gain in")


def _check_per_test(results: list[dict]) -> int:
    """Fail if any single test id rose above its own ceiling."""
    ceilings = _per_test_ceilings()
    counts = _low_counts_by_test(results)

    risen = [(t, n, ceilings.get(t, 0)) for t, n in sorted(counts.items())
             if n > ceilings.get(t, 0)]
    if risen:
        return _report_risen(risen)

    _report_fallen([(t, n, ceilings[t]) for t, n in sorted(counts.items())
                    if t in ceilings and n < ceilings[t]])
    return 0


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
    per_test = _check_per_test(results)
    if per_test:
        return per_test
    return _report_low_ok(low, ceiling)
