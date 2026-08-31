#!/usr/bin/env python3
"""Fail the build when a dependency looks malicious, not merely capable.

osv-scanner and dependency-review answer "does this package have a known
CVE". Neither answers "is this package malware" -- a freshly uploaded
typosquat has no CVE, by definition. GuardDog fills that gap with
heuristics over package code and PyPI metadata.

Two things make this a gate rather than a report:

1. **capability-* findings are ignored.** They are descriptive -- aiohttp
   makes network requests, pip writes executables -- and fire on every
   real library. A gate that reports them is noise, and a noisy gate
   gets disabled.

2. **A download failure is not a pass.** GuardDog reports
   ``{"issues": 0, "errors": {"download-package": "404"}}`` for a package
   it could not fetch. Read naively that is indistinguishable from a
   clean scan, so this gate treats any scan carrying ``errors`` as a
   failure. Measured: every removed typosquat (reuqests, colourama,
   requests3) returns exactly that shape.

Accepted findings live in docs/guarddog-baseline.json, keyed by
(package, rule) so the same rule firing on a different package still
fails.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "guarddog-baseline.json"


def _load_baseline() -> dict[str, dict[str, str]]:
    """Accepted (package, rule) pairs. Missing or malformed is rc=2."""
    if not BASELINE.exists():
        print(f"error: {BASELINE} is missing; cannot evaluate.", file=sys.stderr)
        raise SystemExit(2)
    try:
        raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: {BASELINE} is malformed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("accepted"), dict):
        print(f"error: {BASELINE} must have an 'accepted' object", file=sys.stderr)
        raise SystemExit(2)
    return raw["accepted"]


def scan(package: str) -> dict:
    """Run GuardDog against one package and return its parsed report."""
    proc = subprocess.run(
        [sys.executable, "-m", "guarddog", "pypi", "scan", package,
         "--output-format", "json"],
        capture_output=True, text=True, timeout=900,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"package": package, "_unparseable": proc.stdout[-400:],
                "errors": {"gate": "guarddog produced no parseable JSON"}}


def significant(report: dict) -> list[str]:
    """threat-* and metadata rules that fired. capability-* is ignored."""
    results = report.get("results") or {}
    return sorted(
        rule for rule, hits in results.items()
        if hits and not rule.startswith("capability-")
    )


def check(packages: list[str]) -> int:
    accepted = _load_baseline()
    failures: list[str] = []
    for name in packages:
        report = scan(name)
        pkg = report.get("package", name)

        if report.get("errors"):
            failures.append(
                f"{pkg}: scan did not complete ({report['errors']}). "
                "An unscanned package is not a clean package."
            )
            continue

        allowed = accepted.get(pkg, {})
        for rule in significant(report):
            if rule in allowed:
                print(f"  {pkg}: {rule} (accepted: {allowed[rule][:70]}...)")
            else:
                failures.append(f"{pkg}: {rule}")

    if failures:
        print("\nFAIL: GuardDog flagged dependencies:", file=sys.stderr)
        for line in failures:
            print(f"    {line}", file=sys.stderr)
        print("\n  If a finding is a false positive, add it to", file=sys.stderr)
        print("  docs/guarddog-baseline.json with a written reason.", file=sys.stderr)
        return 1

    print(f"OK: {len(packages)} dependencies clean of threat-* findings")
    return 0


def _packages_from(path: pathlib.Path) -> list[str]:
    """Requirement names only; versions and markers are GuardDog's problem."""
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        for sep in (">=", "==", "<=", "~=", ">", "<", "[", ";"):
            line = line.split(sep)[0]
        if line.strip():
            names.append(line.strip())
    return names


def main(argv: list[str]) -> int:
    """--baseline-file lets CI supply the copy from the trusted base revision.

    On a pull_request event the checkout is the merge commit, so running
    the PR's own baseline would let a PR accept its own findings. Same
    protection the poutine gate uses.
    """
    global BASELINE
    args = list(argv)
    if "--baseline-file" in args:
        i = args.index("--baseline-file")
        BASELINE = pathlib.Path(args[i + 1])
        del args[i:i + 2]
    target = pathlib.Path(args[0]) if args else ROOT / "requirements.txt"
    return check(_packages_from(target))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
