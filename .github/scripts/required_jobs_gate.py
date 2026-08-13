#!/usr/bin/env python3
"""Fail closed unless an exact set of prerequisite Actions jobs succeeded."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _expected_names(raw: str) -> list[str]:
    names = [item.strip() for item in raw.split(",") if item.strip()]
    if not names:
        raise ValueError("expected job list is empty")
    if len(names) != len(set(names)):
        raise ValueError("expected job list contains duplicates")
    return names


def gate_errors(payload: Any, expected: list[str]) -> list[str]:
    """Return every wiring/result error; an empty list means pass."""
    if not isinstance(payload, dict):
        return ["needs payload must be a JSON object"]
    if not payload:
        return ["needs payload is empty"]

    wanted = set(expected)
    actual = set(payload)
    errors = [f"missing prerequisite: {name}" for name in sorted(wanted - actual)]
    errors.extend(f"unexpected prerequisite: {name}" for name in sorted(actual - wanted))

    for name in expected:
        detail = payload.get(name)
        if not isinstance(detail, dict):
            errors.append(f"{name}: result record is missing or malformed")
            continue
        result = detail.get("result")
        if result != "success":
            errors.append(f"{name}: expected success, got {result!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True, help="Comma-separated job IDs")
    parser.add_argument("--env", default="NEEDS_JSON", help="Environment variable carrying toJSON(needs)")
    args = parser.parse_args(argv)

    try:
        expected = _expected_names(args.expected)
        raw = os.environ.get(args.env)
        if raw is None:
            raise ValueError(f"environment variable {args.env} is absent")
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"required-jobs gate input error: {exc}", file=sys.stderr)
        return 2

    errors = gate_errors(payload, expected)
    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1

    print("required-jobs gate passed: " + ", ".join(expected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
