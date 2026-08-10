#!/usr/bin/env python3
"""Report GitHub's open security alerts, so nobody has to remember to look.

Twenty-five releases shipped while thirteen code-scanning alerts sat
open. Every one of those releases was verified: 36/36 CI jobs, a green
preflight, a published artefact with a matching digest. None of that
touches the alert list, which lives in a different tab of a website and
is not part of any pipeline. Ivan found them; the process did not.

Two of the thirteen were real -- unpinned installs of the very scanners
whose verdict gates a release, and LAN URLs carrying a bearer token in
clear text with nothing saying so.

This queries all three feeds and prints what is open. It is
informational by default because the count is not always actionable: a
`note` about `127.0.0.1` in a bridge that exists to listen on loopback
is noise, and a gate that fails on noise gets bypassed within a week.
With ``--max-severity`` it fails on anything at or above the given
level, which is what CI uses.

Needs a token with `security_events` scope. Without one it says so and
exits 0 rather than pretending the repository is clean -- the empty
result and the unauthorised result must never look the same.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

REPO = os.environ.get("ARENA_RELEASE_REPO", "IvanSkainet/arena-agent")
TIMEOUT = 30

SEVERITY_ORDER = ["note", "low", "warning", "medium", "moderate",
                  "high", "error", "critical"]


def _rank(level: str | None) -> int:
    try:
        return SEVERITY_ORDER.index((level or "note").lower())
    except ValueError:
        return 0


def _safe_label(value: object) -> str:
    """A printable type name, with anything that is not one removed.

    The caller hands this a field from the secret-scanning API, which is
    documented to be a display name like ``GitHub Personal Access
    Token``. Trusting that documentation is exactly the assumption worth
    not making in a script whose output goes into CI logs: strip to
    letters, digits, spaces and dashes, and cap the length. A real type
    name survives unchanged; a credential does not survive as one.
    """
    text = str(value or "").strip()
    if not text:
        return "unknown secret type"
    # Allow-list the shape instead of scrubbing characters. A scrub let
    # `ghp_AbCdEf123!@#` through as `ghp_AbCdEf123`, which is most of a
    # token -- proof that "remove the bad characters" is the wrong
    # question when the goal is "never print a credential". A display
    # name is words; a credential is not.
    words = text.split()
    looks_like_a_name = (
        len(words) <= 8
        and all(w.replace("-", "").replace(".", "").isalnum() for w in words)
        and any(w.isalpha() for w in words)
        and not any(len(w) > 24 for w in words)
    )
    if not looks_like_a_name:
        return "secret type withheld (unexpected format)"
    return text[:60]


def _get(path: str) -> tuple[list[dict[str, Any]] | None, str]:
    """Return (alerts, note). `None` means "could not look", not "clean"."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return None, "no GITHUB_TOKEN; cannot read security alerts"
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "arena-security-alerts"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosec B310 -- fixed api.github.com host
            data = json.loads(resp.read().decode("utf-8"))
        return (data, "") if isinstance(data, list) else (None, "unexpected payload")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return None, f"HTTP {exc.code} (token lacks security_events scope?)"
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"unreachable: {exc}"


def collect() -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    notes: list[str] = []

    alerts, note = _get("/code-scanning/alerts?state=open&per_page=100")
    if alerts is None:
        notes.append(f"code scanning: {note}")
    else:
        for a in alerts:
            rule = a.get("rule", {})
            loc = (a.get("most_recent_instance", {}) or {}).get("location", {})
            findings.append({
                "feed": "code-scanning",
                "number": a.get("number"),
                "severity": rule.get("security_severity_level") or rule.get("severity"),
                "id": rule.get("id"),
                "where": f"{loc.get('path')}:{loc.get('start_line')}",
            })

    alerts, note = _get("/dependabot/alerts?state=open&per_page=100")
    if alerts is None:
        notes.append(f"dependabot: {note}")
    else:
        for a in alerts:
            adv = a.get("security_advisory", {})
            dep = (a.get("dependency", {}) or {}).get("package", {})
            findings.append({
                "feed": "dependabot",
                "number": a.get("number"),
                "severity": adv.get("severity"),
                "id": adv.get("summary", "")[:60],
                "where": dep.get("name"),
            })

    alerts, note = _get("/secret-scanning/alerts?state=open&per_page=100")
    if alerts is None:
        notes.append(f"secret scanning: {note}")
    else:
        for a in alerts:
            # CodeQL flagged this path as `py/clear-text-logging-sensitive-data`
            # (high) and it was right to. The secret-scanning payload carries
            # the leaked credential itself in `a["secret"]`, one dictionary
            # key away from a line this script prints. Only the type label is
            # wanted, so take it, sanitise it to a plain identifier, and let
            # the payload go -- a checker for leaked secrets must not be the
            # thing that prints one.
            label = _safe_label(a.get("secret_type_display_name"))
            findings.append({
                "feed": "secret-scanning",
                "number": a.get("number"),
                "severity": "critical",
                "id": label,
                "where": "(see the alert on GitHub)",
            })
    return findings, notes


def main(argv: list[str]) -> int:
    threshold = None
    for i, arg in enumerate(argv):
        if arg == "--max-severity" and i + 1 < len(argv):
            threshold = argv[i + 1]
        elif arg.startswith("--max-severity="):
            threshold = arg.split("=", 1)[1]

    findings, notes = collect()

    for note in notes:
        print(f"security alerts: SKIPPED -- {note}")
    if notes and not findings:
        # Could not look. Say so; do not report a clean repository.
        return 0

    if not findings:
        print("security alerts: OK (no open alerts in any feed)")
        return 0

    by_feed: dict[str, int] = {}
    for f in findings:
        by_feed[f["feed"]] = by_feed.get(f["feed"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(by_feed.items()))
    print(f"security alerts: {len(findings)} open ({summary})")
    for f in sorted(findings, key=lambda x: -_rank(x["severity"])):
        print(f"  #{f['number']} [{f['severity']}] {f['id']}  {f['where']}")

    if threshold:
        over = [f for f in findings if _rank(f["severity"]) >= _rank(threshold)]
        if over:
            print()
            print(f"  {len(over)} at or above '{threshold}' -- these block the build.")
            return 1
        print(f"  none at or above '{threshold}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
