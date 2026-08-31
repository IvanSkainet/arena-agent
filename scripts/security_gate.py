#!/usr/bin/env python3
"""Security-gate checker: parses bandit/semgrep/pip-audit JSON and
exits non-zero when a threshold is breached.

Usage::

    python3 scripts/security_gate.py bandit /tmp/bandit.json
    python3 scripts/security_gate.py semgrep /tmp/semgrep.json
    python3 scripts/security_gate.py pip-audit /tmp/pip-audit.json

Extracted from CI + Makefile so both call the same logic; means
"passes locally" also means "passes in CI". See SECURITY.md for
the gate thresholds:

* bandit: 0 HIGH + 0 MEDIUM; LOW ratcheted against docs/bandit-low-ceiling.txt
  (the count may fall, never rise). Implemented in scripts/bandit_gate.py.
* semgrep: 0 findings across all 9 rule packs
* pip-audit: 0 CVEs in runtime + full-extras deps

Exit codes:
    0  clean
    1  threshold breached
    2  usage error / malformed JSON / file missing
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"error: report file not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            print(f"error: report root must be an object: {path}", file=sys.stderr)
            sys.exit(2)
        return data
    except Exception as e:  # noqa: BLE001
        print(f"error: could not parse {path}: {e}", file=sys.stderr)
        sys.exit(2)


from bandit_gate import check_bandit  # noqa: E402  (re-export for the CLI)


def check_semgrep(report_path: str) -> int:
    """Fail on any ERROR or WARNING across all rule packs.

    Every existing false-positive line carries a specific-rationale
    ``# nosemgrep: <rule> -- <reason>`` annotation. New findings mean
    either a real bug or a new rule that needs its own annotation
    (with a code-review-visible rationale)."""
    d = _load(report_path)
    results = d.get("results")
    errors = d.get("errors")
    if not isinstance(results, list) or not isinstance(errors, list):
        print("error: semgrep report must contain results and errors arrays", file=sys.stderr)
        return 2
    if errors:
        print(f"error: semgrep reported {len(errors)} execution/config error(s)", file=sys.stderr)
        return 2
    if any(not isinstance(item, dict) for item in results):
        print("error: semgrep result must be an object", file=sys.stderr)
        return 2
    for item in results:
        start = item.get("start")
        if (
            not isinstance(item.get("check_id"), str)
            or not isinstance(item.get("path"), str)
            or not isinstance(start, dict)
            or not isinstance(start.get("line"), int)
        ):
            print("error: semgrep result has missing/invalid required fields", file=sys.stderr)
            return 2
    print(f"semgrep findings: {len(results)}")
    if not results:
        print("OK: semgrep clean across all rule packs")
        return 0
    print(
        "FAIL: semgrep found new findings; each needs either a fix "
        "or a per-line `# nosemgrep: <rule> -- <rationale>` "
        "annotation."
    )
    by_rule: dict[str, list] = {}
    for r in results:
        rid = r.get("check_id", "?").split(".")[-1]
        by_rule.setdefault(rid, []).append(r)
    for rid, lst in sorted(by_rule.items(), key=lambda x: -len(x[1])):
        print(f"  {len(lst)}x {rid}")
        for f in lst[:3]:
            print(f"      {f['path']}:{f['start']['line']}")
    return 1


def check_pip_audit(report_path: str) -> int:
    """Fail on any CVE in the runtime + full-extras deps."""
    d = _load(report_path)
    deps = d.get("dependencies")
    if not isinstance(deps, list):
        print("error: pip-audit report must contain a dependencies array", file=sys.stderr)
        return 2
    if any(not isinstance(dep, dict) for dep in deps):
        print("error: pip-audit dependency must be an object", file=sys.stderr)
        return 2
    for dep in deps:
        vulns = dep.get("vulns")
        if (
            not isinstance(dep.get("name"), str)
            or not isinstance(dep.get("version"), str)
            or not isinstance(vulns, list)
            or any(not isinstance(vuln, dict) for vuln in vulns)
        ):
            print("error: pip-audit dependency has missing/invalid required fields", file=sys.stderr)
            return 2
    any_cve = False
    for dep in deps:
        vulns = dep.get("vulns") or []
        if vulns:
            any_cve = True
            for v in vulns:
                print(
                    f"FAIL: CVE in {dep['name']}=={dep['version']}: "
                    f"{v.get('id')} -- fix: {v.get('fix_versions')}"
                )
    if any_cve:
        print(
            "\nUpgrade the affected dep(s) to a fixed version and "
            "re-run `make security-pip-audit`."
        )
        return 1
    print(f"OK: pip-audit clean ({len(deps)} deps scanned)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("bandit", "semgrep", "pip-audit"):
        print(__doc__, file=sys.stderr)
        return 2
    tool = argv[1]
    if tool == "bandit":
        return check_bandit(argv[2])
    if tool == "semgrep":
        return check_semgrep(argv[2])
    return check_pip_audit(argv[2])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
