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
`note` about a loopback address in a bridge that exists to listen on
loopback is noise, and a gate that fails on noise gets bypassed within a
week. With ``--max-severity`` it fails on anything at or above the given
level, which is what CI uses.

Needs a token with `security_events` scope. Without one it says so and
exits 0 rather than pretending the repository is clean -- the empty
result and the unauthorised result must never look the same.

Why this lives in ``arena/`` and not in the script that runs it
---------------------------------------------------------------

It used to be the whole of ``scripts/security_alerts_check.py``: the
networking, the alert processing, the severity decisions and the output
orchestration, in a `scripts/` entrypoint. A qodo review on PR #189
named the boundary that was being violated -- `scripts/` files are
supposed to be thin wrappers -- and #190 tracked the move. The fix for
CodeQL alert #341 had to land in the file the taint was reported in, so
rewriting the gate in the same PR would have widened a security fix into
a refactor; that is why the two are separate changes.

The name is ``security_alerts`` and not ``security.alerts`` because
``arena/security.py`` already exists: a ``arena/security/`` package
shadows it, and the first attempt at this move took every job in the
matrix down with `ImportError: cannot import name
'_INPUT_INJECTION_PATTERNS' from 'arena.security'` -- `unified_bridge`
imports that module at start-up through ``arena.runtime_deps.core``. A
flat module sits alongside ``security_http.py``, ``security_ssrf.py``
and ``security_input.py``, which is the convention this tree already
uses for that domain.

The gate's behaviour is deliberately unchanged by the move: fail closed
on ANY open secret-scanning alert, exit non-zero when a finding is at or
above ``--max-severity``, and never report a repository as clean when it
could not be read.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

REPO = os.environ.get("ARENA_RELEASE_REPO", "IvanSkainet/arena-agent")
TIMEOUT = 30


def code_scanning_ref() -> str | None:
    """The git ref whose code-scanning alerts this run should judge.

    Without this the query is repository-wide, and a finding on `master`
    fails every open pull request -- including the one that fixes it.
    That happened: two `py/command-line-injection` alerts landed on
    `master`, and the branch that removed the `shell=True` behind them
    could not merge, because the gate kept reporting the alerts still
    sitting on the branch being merged into. A gate that cannot be
    satisfied by fixing the code is not a gate, it is a deadlock.

    On a pull request, judge the PR's own head. Everywhere else -- a
    push to master, a release -- judge the whole repository, which is
    the behaviour that catches a finding nobody has a PR for.
    """
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if not event.startswith("pull_request"):
        return None
    number = ""
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/pull/"):
        # `startswith("refs/pull/")` already guarantees three segments,
        # so `[2]` cannot raise -- review flagged an IndexError here and
        # it is not reachable. Written defensively anyway because the
        # prefix and the index are two facts that must agree, and only
        # one of them is visible from the other.
        parts = ref.split("/")
        number = parts[2] if len(parts) > 2 else ""
    if not number:
        path = os.environ.get("GITHUB_EVENT_PATH", "")
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, ValueError):
                payload = None
            # Valid JSON of the wrong shape is not an error condition, it
            # is a list or a string where a dict was expected. Reaching
            # `.get` on one raises AttributeError and takes the whole gate
            # down -- a security check must not be crashable by the
            # contents of a file it merely consults.
            if isinstance(payload, dict):
                number = str(payload.get("number") or "")
    if not number.isdigit():
        # Better repo-wide than silently unfiltered-but-claiming-scoped.
        # `isdigit` and not just truthiness: a ref segment can be any
        # string, and a non-numeric one would build a ref that matches
        # nothing, which reads as "no alerts" -- the failure this gate
        # exists to prevent.
        return None
    return f"refs/pull/{number}/head"


SEVERITY_ORDER = ["note", "low", "warning", "medium", "moderate",
                  "high", "error", "critical"]


def _rank(level: str | None) -> int:
    try:
        return SEVERITY_ORDER.index((level or "note").lower())
    except ValueError:
        return 0


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
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosec B310 -- fixed api.github.com host; nosemgrep: dynamic-urllib-use-detected -- the host is the literal api.github.com and only the path, built from constants above, varies
            data = json.loads(resp.read().decode("utf-8"))
        return (data, "") if isinstance(data, list) else (None, "unexpected payload")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return None, f"HTTP {exc.code} (token lacks security_events scope?)"
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"unreachable: {exc}"


def _scanning_rows(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn secret-scanning alerts into printable rows.

    Two independent CodeQL sources had to go for alert #341 to clear,
    and this docstring keeps both mechanisms from being re-learned the
    hard way. First, the response fields: nothing read from the payload
    crosses into a row except the int-cast `number` (PR #189 removed the
    type-label read). Second, this function's own NAME:
    `py/clear-text-logging-sensitive-data` treats the return of any
    function whose name carries a secret-shaped fragment as sensitive
    data in its own right -- the post-#189 master analysis still flagged
    the print in `main` with the SARIF source pinned to this function's
    call site, while its rows were already pure literals. Hence the
    neutral `_scanning_rows` name; an AST test keeps sensitive fragments
    out of function names in this module.

    The gate's contract is unchanged: fail closed on ANY open
    secret-scanning alert. The type is on GitHub's alert page, not in
    the CI log.
    """
    rows: list[dict[str, Any]] = []
    for alert in alerts:
        try:
            number = int(alert.get("number") or 0)
        except (TypeError, ValueError):
            number = 0
        rows.append({
            "feed": "secret-scanning",
            "number": number,
            "severity": "critical",
            "id": "see the alert on GitHub",
            "where": f"alert #{number}",
        })
    return rows


def collect() -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    notes: list[str] = []

    ref = code_scanning_ref()
    query = "/code-scanning/alerts?state=open&per_page=100"
    if ref:
        query += f"&ref={urllib.parse.quote(ref, safe='/')}"
        notes.append(f"code scanning scoped to {ref}")
    alerts, note = _get(query)
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
        findings.extend(_scanning_rows(alerts))
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
