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


def _ceiling() -> int:
    if not CEILING_FILE.exists():
        print(f"error: {CEILING_FILE} is missing; the poutine ratchet has no "
              f"baseline. A gate that cannot evaluate itself must fail.",
              file=sys.stderr)
        raise SystemExit(2)
    try:
        return int(CEILING_FILE.read_text(encoding="utf-8").split("#")[0].strip())
    except ValueError as exc:
        print(f"error: {CEILING_FILE} is malformed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _findings(report_path: str) -> list[dict]:
    try:
        data = json.loads(pathlib.Path(report_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: poutine report not found: {report_path}", file=sys.stderr)
        raise SystemExit(2) from None
    except json.JSONDecodeError as exc:
        print(f"error: poutine report is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        print("error: poutine report must be an object with a findings array",
              file=sys.stderr)
        raise SystemExit(2)
    return data["findings"]


def _describe(findings: list[dict]) -> None:
    by_rule = collections.Counter(f.get("rule_id", "?") for f in findings)
    for rule, n in by_rule.most_common():
        print(f"  {n:3d}  {rule}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="poutine.json")
    args = ap.parse_args(argv)

    findings = _findings(args.report)
    ceiling = _ceiling()
    total = len(findings)

    print(f"poutine findings: {total} (ceiling {ceiling})")
    _describe(findings)

    if total > ceiling:
        print(f"\nFAIL: poutine findings rose to {total}, ceiling is {ceiling}.")
        print("  Fix the new finding, or raise docs/poutine-ceiling.txt in the")
        print("  same PR with a written justification.")
        for f in findings:
            meta = f.get("meta", {}) or {}
            print(f"    {f.get('rule_id')} {meta.get('path')}:{meta.get('line')} "
                  f"job={meta.get('job')}")
        return 1

    if total < ceiling:
        print(f"\nOK: below the ceiling. Lower docs/poutine-ceiling.txt to "
              f"{total} to lock the gain in.")
    else:
        print("\nOK: at the ceiling.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
