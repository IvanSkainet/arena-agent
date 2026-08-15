#!/usr/bin/env python3
"""Fail-closed execution/report contracts for advisory security scanners."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SEVERITIES = ("unknown", "negligible", "low", "medium", "high", "critical")


class ContractError(ValueError):
    pass


def validate_exit(tool: str, code: int, allowed: set[int]) -> None:
    if code not in allowed:
        raise ContractError(
            f"{tool} execution failed with exit {code}; allowed policy exits: "
            + ",".join(str(item) for item in sorted(allowed))
        )


def load_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"report missing: {path}")
    if path.stat().st_size == 0:
        raise ContractError(f"report empty: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"report is not valid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"report root must be an object: {path}")
    return value


def validate_osv(data: dict[str, Any]) -> tuple[int, Counter[str]]:
    results = data.get("results")
    if not isinstance(results, list):
        raise ContractError("OSV report must contain a results array")
    if any(not isinstance(item, dict) for item in results):
        raise ContractError("OSV result entries must be objects")
    return len(results), Counter({"finding": len(results)})


def validate_cyclonedx(data: dict[str, Any]) -> tuple[int, Counter[str]]:
    if data.get("bomFormat") != "CycloneDX":
        raise ContractError("CycloneDX report has wrong or missing bomFormat")
    if not isinstance(data.get("specVersion"), str):
        raise ContractError("CycloneDX report has no specVersion")
    components = data.get("components")
    if not isinstance(components, list):
        raise ContractError("CycloneDX report must contain a components array")
    if any(not isinstance(item, dict) for item in components):
        raise ContractError("CycloneDX component entries must be objects")
    return len(components), Counter({"component": len(components)})


def validate_grype(data: dict[str, Any]) -> tuple[int, Counter[str]]:
    matches = data.get("matches")
    if not isinstance(matches, list):
        raise ContractError("Grype report must contain a matches array")
    counts: Counter[str] = Counter()
    for match in matches:
        if not isinstance(match, dict) or not isinstance(match.get("vulnerability"), dict):
            raise ContractError("Grype match is missing vulnerability metadata")
        severity = str(match["vulnerability"].get("severity") or "unknown").lower()
        if severity not in SEVERITIES:
            raise ContractError(f"Grype emitted unknown severity: {severity}")
        counts[severity] += 1
    return len(matches), counts


def validate_sarif(data: dict[str, Any]) -> tuple[int, Counter[str]]:
    if data.get("version") != "2.1.0":
        raise ContractError("SARIF report must use version 2.1.0")
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ContractError("SARIF report must contain at least one run")
    counts: Counter[str] = Counter()
    total = 0
    for run in runs:
        if not isinstance(run, dict):
            raise ContractError("SARIF run must be an object")
        tool = run.get("tool")
        if not isinstance(tool, dict) or not isinstance(tool.get("driver"), dict):
            raise ContractError("SARIF run is missing tool.driver")
        results = run.get("results", [])
        if not isinstance(results, list):
            raise ContractError("SARIF run results must be an array")
        for result in results:
            if not isinstance(result, dict):
                raise ContractError("SARIF result must be an object")
            level = str(result.get("level") or "warning").lower()
            if level not in {"none", "note", "warning", "error"}:
                raise ContractError(f"SARIF emitted unknown level: {level}")
            counts[level] += 1
            total += 1
    return total, counts


VALIDATORS = {
    "osv": validate_osv,
    "cyclonedx": validate_cyclonedx,
    "grype": validate_grype,
    "sarif": validate_sarif,
}


def policy_failures(kind: str, counts: Counter[str], block: set[str]) -> int:
    if kind == "grype":
        return sum(count for level, count in counts.items() if level in block)
    if kind == "sarif":
        return sum(count for level, count in counts.items() if level in block)
    if kind == "osv":
        return counts["finding"] if "finding" in block else 0
    return 0


def _csv_ints(raw: str) -> set[int]:
    try:
        values = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError as exc:
        raise ContractError("allowed exits must be comma-separated integers") from exc
    if not values:
        raise ContractError("allowed exits cannot be empty")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True)
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--allowed-exits", default="0")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--format", choices=sorted(VALIDATORS))
    parser.add_argument("--block", default="")
    args = parser.parse_args(argv)
    try:
        if args.exit_code is not None:
            validate_exit(args.tool, args.exit_code, _csv_ints(args.allowed_exits))
        if (args.report is None) != (args.format is None):
            raise ContractError("--report and --format must be supplied together")
        if args.report is not None and args.format is not None:
            data = load_object(args.report)
            total, counts = VALIDATORS[args.format](data)
            block = {item.strip().lower() for item in args.block.split(",") if item.strip()}
            fatal = policy_failures(args.format, counts, block)
            print(
                json.dumps(
                    {
                        "tool": args.tool,
                        "format": args.format,
                        "records": total,
                        "counts": dict(sorted(counts.items())),
                        "blocking": fatal,
                    },
                    sort_keys=True,
                )
            )
            if fatal:
                print(f"policy failure: {args.tool} emitted {fatal} blocking finding(s)", file=sys.stderr)
                return 1
        return 0
    except ContractError as exc:
        print(f"contract failure: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
