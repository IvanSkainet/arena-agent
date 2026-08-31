#!/usr/bin/env python3
"""Ratchet poutine findings so the count can fall but never rise.

Measured on master 16091e32: 8 findings, all understood.

* 7x `github_action_from_unverified_creator_used` -- actions from creators
  GitHub has not verified. Every one is already pinned to a full commit SHA,
  which is the mitigation that matters; the rule is really "you depend on
  small vendors" (Socket, gitleaks, actionlint, zizmor, osv-scanner,
  setup-android x2). Dropping them costs more security than it buys.
* 1x `untrusted_checkout_exec` in `boe-contract` -- pip install after a
  checkout on a `pull_request` trigger. Real category, but that workflow is
  path-filtered and pip installs from a pinned lock, so it is accepted debt
  rather than an open door.

The point of the ratchet is that finding number 9 has to be looked at by a
human, instead of joining a pile nobody reads. As with the bandit LOW ceiling,
a missing baseline is a broken gate (exit 2), never a silent pass.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CEILING_FILE = ROOT / "docs" / "poutine-ceiling.txt"


def _read_text(path: pathlib.Path) -> str:
    """Read a committed input, treating any read failure as a broken gate."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: {path} is missing; the poutine ratchet has no baseline. "
              f"A gate that cannot evaluate itself must fail.", file=sys.stderr)
        raise SystemExit(2) from None
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: {path} could not be read: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _ceiling(ceiling_file: pathlib.Path | None = None) -> int:
    path = ceiling_file or CEILING_FILE
    try:
        return int(_read_text(path).split("#")[0].strip())
    except ValueError as exc:
        print(f"error: {path} is malformed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _parse_report(report_path: str) -> dict:
    try:
        data = json.loads(_read_text(pathlib.Path(report_path)))
    except json.JSONDecodeError as exc:
        print(f"error: poutine report is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        print("error: poutine report must be an object with a findings array",
              file=sys.stderr)
        raise SystemExit(2)
    return data


def _validate(findings: list) -> None:
    """Reject malformed entries up front.

    A findings array containing a non-object would otherwise blow up later
    with an AttributeError, which reads as a crashed job rather than the
    documented fail-closed exit 2.
    """
    for i, f in enumerate(findings):
        if not isinstance(f, dict) or not isinstance(f.get("rule_id"), str):
            print(f"error: poutine finding {i} is malformed: {f!r}", file=sys.stderr)
            raise SystemExit(2)


def _findings(report_path: str) -> list[dict]:
    findings = _parse_report(report_path)["findings"]
    _validate(findings)
    return findings


def _describe(findings: list[dict]) -> None:
    by_rule = collections.Counter(f.get("rule_id", "?") for f in findings)
    for rule, n in by_rule.most_common():
        print(f"  {n:3d}  {rule}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="poutine.json")
    ap.add_argument("--ceiling-file", default=None,
                    help="path to the ceiling file; defaults to the one in "
                         "this checkout. CI passes the base-revision copy so a "
                         "pull request cannot raise its own ceiling.")
    return ap.parse_args(argv)


def _report_regression(findings: list[dict], total: int, ceiling: int) -> int:
    print(f"\nFAIL: poutine findings rose to {total}, ceiling is {ceiling}.")
    print("  Fix the new finding, or raise docs/poutine-ceiling.txt in the")
    print("  same PR with a written justification.")
    for f in findings:
        meta = f.get("meta", {}) or {}
        print(f"    {f.get('rule_id')} {meta.get('path')}:{meta.get('line')} "
              f"job={meta.get('job')}")
    return 1


def _report_ok(total: int, ceiling: int) -> int:
    if total < ceiling:
        print(f"\nOK: below the ceiling. Lower docs/poutine-ceiling.txt to "
              f"{total} to lock the gain in.")
    else:
        print("\nOK: at the ceiling.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    findings = _findings(args.report)
    ceiling = _ceiling(pathlib.Path(args.ceiling_file) if args.ceiling_file else None)
    total = len(findings)

    print(f"poutine findings: {total} (ceiling {ceiling})")
    _describe(findings)

    if total > ceiling:
        return _report_regression(findings, total, ceiling)
    return _report_ok(total, ceiling)


if __name__ == "__main__":
    sys.exit(main())
