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

* bandit: 0 HIGH + 0 MEDIUM; LOW allowed (code hygiene noise)
* semgrep: 0 findings across all 9 rule packs
* pip-audit: 0 CVEs in runtime + full-extras deps

Exit codes:
    0  clean
    1  threshold breached
    2  usage error / malformed JSON / file missing
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"error: report file not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(p.read_text())
    except Exception as e:  # noqa: BLE001
        print(f"error: could not parse {path}: {e}", file=sys.stderr)
        sys.exit(2)


def check_bandit(report_path: str) -> int:
    """Fail on any HIGH or MEDIUM finding. LOW is code-hygiene
    noise (try/except pass, subprocess-without-shell, partial
    path) that we tolerate to keep the sweep focused on real
    security issues."""
    d = _load(report_path)
    results = d.get("results", [])
    by_sev: dict[str, int] = {}
    for r in results:
        sev = r.get("issue_severity", "?")
        by_sev[sev] = by_sev.get(sev, 0) + 1
    print(f"bandit findings by severity: {by_sev}")
    fatal = by_sev.get("HIGH", 0) + by_sev.get("MEDIUM", 0)
    if fatal:
        print(f"FAIL: bandit found {fatal} HIGH/MEDIUM findings")
        for r in results:
            if r.get("issue_severity") in ("HIGH", "MEDIUM"):
                print(
                    f"  {r['filename']}:{r['line_number']} "
                    f"[{r['test_id']}] "
                    f"{r.get('issue_text','')[:120]}"
                )
        print(
            "\nEach finding needs either:\n"
            "  - a real fix (preferred), or\n"
            "  - a per-line `# nosec <ID> -- <specific rationale>` "
            "annotation after verifying the line is safe.\n"
            "See SECURITY.md for the review workflow."
        )
        return 1
    print("OK: bandit clean at HIGH+MEDIUM")
    return 0


def check_semgrep(report_path: str) -> int:
    """Fail on any ERROR or WARNING across all rule packs.

    Every existing false-positive line carries a specific-rationale
    ``# nosemgrep: <rule> -- <reason>`` annotation. New findings mean
    either a real bug or a new rule that needs its own annotation
    (with a code-review-visible rationale)."""
    d = _load(report_path)
    results = d.get("results", [])
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
    deps = d.get("dependencies", [])
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
