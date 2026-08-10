#!/usr/bin/env python3
"""Fail when an alert is dismissed on the website and nowhere else.

The alert gate that shipped in v4.169.25 asks GitHub for
``state=open`` and, finding nothing, prints "OK (no open alerts in any
feed)". It printed exactly that today, with 294 alerts sitting in the
dismissed state -- 78 of them high or critical. Ivan could see them; the
gate could not, because pressing Dismiss is precisely the act of taking
an alert out of the query the gate runs.

That makes a button on a web page a silent override of the release
gate. Every finding from here on can be closed by hand, and CI stays
green, and the closing leaves no trace in anything a reviewer reads.
The thirteen open alerts were a hole in coverage; this is worse,
because it looks like coverage.

So dismissals become data in the tree. ``security_dismissals.json``
records, per rule id, how many alerts were dismissed and under which
reason. This compares that file to live GitHub state and fails when:

* a rule gains dismissals that were never recorded, or
* a rule is dismissed that the file does not mention at all.

Dismissing stays allowed. It just has to arrive as a commit, be visible
in a diff, and survive review like any other change. A count that
*shrinks* never fails -- fixing an alert properly must not require
editing a baseline, or the baseline becomes a chore and then a lie.

No token, or a token without ``security_events``: this reports SKIPPED
and exits 0. The unauthorised result and the clean result must never
look the same -- that confusion is what the earlier gate was built to
avoid, and it applies here unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = os.environ.get("ARENA_RELEASE_REPO", "IvanSkainet/arena-agent")
BASELINE = Path(__file__).resolve().parent.parent / "security_dismissals.json"
TIMEOUT = 30
SEVERITY_ORDER = ["note", "low", "warning", "medium", "moderate",
                  "high", "error", "critical"]


def _rank(level: str | None) -> int:
    try:
        return SEVERITY_ORDER.index((level or "note").lower())
    except ValueError:
        return 0


def _fetch_dismissed() -> tuple[list[dict[str, Any]] | None, str]:
    """Every dismissed alert, paged. `None` means "could not look"."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return None, "no GITHUB_TOKEN; cannot read dismissed alerts"
    out: list[dict[str, Any]] = []
    for page in range(1, 21):
        url = (f"https://api.github.com/repos/{REPO}/code-scanning/alerts"
               f"?state=dismissed&per_page=100&page={page}")
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "arena-dismissed-alerts"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosec B310 -- fixed api.github.com host
                batch = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None, f"HTTP {exc.code} (token lacks security_events scope?)"
            return None, f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return None, f"unreachable: {exc}"
        if not isinstance(batch, list):
            return None, "unexpected payload"
        if not batch:
            break
        out.extend(batch)
    return out, ""


def summarise(alerts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse alerts into the per-rule shape the baseline stores.

    Keyed by rule id, not alert number: numbers are reassigned when an
    analysis is re-run, so a baseline keyed by number would churn on
    every scan and teach everyone to regenerate it without reading.
    """
    rules: dict[str, dict[str, Any]] = {}
    for alert in alerts:
        rule = alert.get("rule") or {}
        rid = str(rule.get("id") or "unknown")
        sev = rule.get("security_severity_level") or rule.get("severity") or "note"
        reason = str(alert.get("dismissed_reason") or "unspecified")
        entry = rules.setdefault(rid, {"severity": sev, "dismissed": 0, "reasons": {}})
        entry["dismissed"] += 1
        entry["reasons"][reason] = entry["reasons"].get(reason, 0) + 1
        if _rank(sev) > _rank(entry["severity"]):
            entry["severity"] = sev
    for entry in rules.values():
        entry["reasons"] = dict(sorted(entry["reasons"].items()))
    return dict(sorted(rules.items()))


def load_baseline() -> dict[str, dict[str, Any]]:
    if not BASELINE.exists():
        return {}
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    rules = data.get("rules")
    return rules if isinstance(rules, dict) else {}


def compare(live: dict[str, dict[str, Any]],
            base: dict[str, dict[str, Any]]) -> list[str]:
    """Rules dismissed more than the tree admits to. Empty means fine."""
    problems: list[str] = []
    for rid, entry in live.items():
        recorded = base.get(rid)
        if recorded is None:
            problems.append(
                f"{rid} [{entry['severity']}]: {entry['dismissed']} dismissed, "
                f"not recorded in {BASELINE.name} at all")
            continue
        known = int(recorded.get("dismissed") or 0)
        if entry["dismissed"] > known:
            problems.append(
                f"{rid} [{entry['severity']}]: {entry['dismissed']} dismissed, "
                f"{known} recorded ({entry['dismissed'] - known} new)")
    return problems


def write_baseline(live: dict[str, dict[str, Any]]) -> None:
    data: dict[str, Any] = {}
    if BASELINE.exists():
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
    data["rules"] = live
    BASELINE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    update = "--update" in argv

    alerts, note = _fetch_dismissed()
    if alerts is None:
        print(f"dismissed alerts: SKIPPED -- {note}")
        return 0

    live = summarise(alerts)
    total = sum(e["dismissed"] for e in live.values())

    if update:
        write_baseline(live)
        print(f"dismissed alerts: recorded {total} dismissals "
              f"across {len(live)} rules into {BASELINE.name}")
        return 0

    base = load_baseline()
    if not base and total:
        print(f"dismissed alerts: {BASELINE.name} is missing or empty while "
              f"GitHub reports {total} dismissals -- run --update and commit it.")
        return 1

    problems = compare(live, base)
    if not problems:
        print(f"dismissed alerts: OK ({total} dismissals across "
              f"{len(live)} rules, all recorded)")
        return 0

    print(f"dismissed alerts: {len(problems)} rule(s) dismissed beyond the record")
    for line in problems:
        print(f"  {line}")
    print()
    print("  An alert dismissed on the website and nowhere else is a release")
    print("  gate overridden by a button press. Re-open it, or record the")
    print("  decision: python scripts/dismissed_alerts_gate.py --update")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
