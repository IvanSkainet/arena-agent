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

Code scanning and Dependabot use the job's read-only ``GITHUB_TOKEN``
(``security-events: read`` and ``vulnerability-alerts: read``). GitHub
does not let ``GITHUB_TOKEN`` read secret-scanning alerts, so that feed
uses a separate ``SECRET_SCANNING_TOKEN`` with only the repository's
Secret scanning alerts: read permission. Missing credentials are reported
explicitly; strict CI mode fails rather than mistaking an unreadable feed
for a clean one.

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
'_INPUT_INJECTION_PATTERNS' from 'arena.security'`, raised while
``unified_bridge`` was still assembling its runtime facade at start-up.
A flat module sits alongside ``security_http.py``, ``security_ssrf.py``
and ``security_input.py``, which is the convention this tree already
uses for that domain.

(The facade namespace is named in full in the test that pins this, not
here: `test_runtime_dependency_namespace_is_facade_only` fails any
``arena/`` file outside the facade that mentions it, prose included.)

The gate's behaviour is deliberately unchanged by the move: fail closed
on ANY open secret-scanning alert, exit non-zero when a finding is at or
above ``--max-severity``, and never report a repository as clean when it
could not be read.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, TypeGuard, cast

from arena import security_manifest_proof as manifest_proof
from arena.security_advisory_proof import advisory_floor

REPO = os.environ.get("ARENA_RELEASE_REPO", "IvanSkainet/arena-agent")
TIMEOUT = 30


def _number_from_ref(ref: str) -> str:
    if not ref.startswith("refs/pull/"):
        return ""
    parts = ref.split("/")
    return parts[2] if len(parts) > 2 else ""


def _event_payload(payload_path: str | None = None) -> dict[str, Any] | None:
    path = payload_path or os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _number_from_payload(payload_path: str) -> str:
    payload = _event_payload(payload_path)
    return str(payload.get("number") or "") if payload else ""


def _pull_request_number() -> str:
    if not os.environ.get("GITHUB_EVENT_NAME", "").startswith("pull_request"):
        return ""
    number = _number_from_ref(os.environ.get("GITHUB_REF", ""))
    if not number:
        number = _number_from_payload(os.environ.get("GITHUB_EVENT_PATH", ""))
    return number if number.isdigit() else ""


def _is_fork_pull_request() -> bool:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return False
    payload = _event_payload() or {}
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict):
        return False
    head = pull_request.get("head") or {}
    base = pull_request.get("base") or {}
    head_repo = (head.get("repo") or {}).get("full_name")
    base_repo = (base.get("repo") or {}).get("full_name")
    return bool(head_repo and base_repo and head_repo != base_repo)


def code_scanning_ref() -> str | None:
    """
    The PR head ref, or None when the run is not safely scopeable.

    Repository-wide CodeQL findings would otherwise deadlock the PR that
    fixes them. A malformed event falls back to repo-wide inspection rather
    than constructing a ref that would look like an empty alert list.
    """
    if not os.environ.get("GITHUB_EVENT_NAME", "").startswith("pull_request"):
        return None
    number = _number_from_ref(os.environ.get("GITHUB_REF", ""))
    if not number:
        number = _number_from_payload(os.environ.get("GITHUB_EVENT_PATH", ""))
    return f"refs/pull/{number}/head" if number.isdigit() else None


SEVERITY_ORDER = ["note", "low", "warning", "medium", "moderate",
                  "high", "error", "critical"]


def _rank(level: str | None) -> int:
    try:
        return SEVERITY_ORDER.index((level or "note").lower())
    except ValueError:
        return 0


def _request_json(path: str) -> tuple[Any, str]:
    """Return (alerts, note). `None` means "could not look", not "clean"."""
    secret_feed = path.startswith("/secret-scanning/")
    token_name = "SECRET_SCANNING_TOKEN" if secret_feed else "GITHUB_TOKEN"
    token = os.environ.get(token_name)
    if not secret_feed:
        token = token or os.environ.get("GH_TOKEN")
    if not token:
        return None, f"no {token_name}; cannot read security alerts"
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "arena-security-alerts"})
    try:
        # Both annotations say the same thing: the host is the literal
        # api.github.com built above, and only the path varies, from the
        # constants in `collect`. Neither scanner can see that from the
        # Request object alone.
        # nosec B310 -- fixed api.github.com host
        # nosemgrep: dynamic-urllib-use-detected -- fixed api.github.com host
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosec B310  # nosemgrep: dynamic-urllib-use-detected
            data = json.loads(resp.read().decode("utf-8"))
        return data, ""
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            permission = ("secret_scanning_alerts" if secret_feed else
                         "security_events or vulnerability_alerts")
            return None, f"HTTP {exc.code} (token may lack {permission}: read)"
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"unreachable: {exc}"


def _get(path: str) -> tuple[list[dict[str, Any]] | None, str]:
    data, note = _request_json(path)
    return (data, note) if isinstance(data, list) else (None, note or "unexpected payload")


def _get_object(path: str) -> tuple[dict[str, Any] | None, str]:
    data, note = _request_json(path)
    return (data, note) if isinstance(data, dict) else (None, note or "unexpected payload")


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


def _code_row(alert: dict[str, Any]) -> dict[str, Any]:
    rule = alert.get("rule", {})
    location = (alert.get("most_recent_instance", {}) or {}).get("location", {})
    return {
        "feed": "code-scanning",
        "number": alert.get("number"),
        "severity": rule.get("security_severity_level") or rule.get("severity"),
        "id": rule.get("id"),
        "where": f"{location.get('path')}:{location.get('start_line')}",
    }


def _dependabot_row(alert: dict[str, Any]) -> dict[str, Any]:
    advisory = alert.get("security_advisory", {})
    vulnerability = alert.get("security_vulnerability", {})
    dependency = alert.get("dependency", {}) or {}
    package = dependency.get("package", {}) or {}
    patched = vulnerability.get("first_patched_version") or {}
    return {
        "feed": "dependabot",
        "number": alert.get("number"),
        "severity": advisory.get("severity"),
        "id": advisory.get("summary", "")[:60],
        "where": package.get("name"),
        "ecosystem": package.get("ecosystem"),
        "manifest_path": dependency.get("manifest_path"),
        "first_patched_version": patched.get("identifier"),
        "proof_floor": advisory_floor(advisory, str(package.get("name", "")),
                                      str(package.get("ecosystem", ""))),
        "fixed_by_pr": False,
    }


def _nonempty_text(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


def _dependabot_fix_identity(
    row: dict[str, Any],
) -> tuple[str, str, str] | None:
    if row.get("ecosystem") != "pip":
        return None
    fields = (
        row.get("manifest_path"),
        row.get("where"),
        row.get("proof_floor"),
    )
    if not all(map(_nonempty_text, fields)):
        return None
    return cast(tuple[str, str, str], fields)


def _event_head_sha() -> str:
    payload = _event_payload() or {}
    pr = payload.get("pull_request")
    head = pr.get("head") if isinstance(pr, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    return sha if isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha) else ""


def _verified_manifest_fix(
    row: dict[str, Any], changed: dict[str, dict[str, Any]],
    tree: dict[str, Any], cache: dict[str, str | None],
) -> bool:
    identity = _dependabot_fix_identity(row)
    if identity is None:
        return False
    path, package, minimum = identity
    if path not in changed:
        return False
    state, sha = manifest_proof.tree_manifest(tree, path)
    if state == "absent":
        return changed[path].get("status") == "removed"
    if state != "file":
        return False
    if sha not in cache:
        blob, _ = _get_object(f"/git/blobs/{sha}")
        cache[sha] = manifest_proof.decode_manifest(blob, sha) if blob else None
    text = cache[sha]
    return text is not None and manifest_proof.manifest_fixes(path, text, package, minimum)


def _fixed_dependabot_alerts_by_pr(
    rows: list[dict[str, Any]],
) -> tuple[set[str], str]:
    """Prove fixes using full blobs from the event's exact head, never a diff."""
    number = _pull_request_number()
    if not number or not rows:
        return set(), ""
    sha = _event_head_sha()
    if not sha:
        return set(), "dependabot PR comparison unavailable: no exact event head SHA"
    files, note = _get(f"/pulls/{number}/files?per_page=100")
    if files is None:
        return set(), f"dependabot PR comparison unavailable: {note}"
    tree, note = _get_object(f"/git/trees/{sha}?recursive=1")
    if tree is None:
        return set(), f"dependabot PR comparison unavailable: {note}"
    changed = {item["filename"]: item for item in files
               if isinstance(item.get("filename"), str)}
    cache: dict[str, str | None] = {}
    fixed = {str(row.get("number")) for row in rows
             if _verified_manifest_fix(row, changed, tree, cache)}
    summary = f"dependabot PR fixes checked: {len(fixed)} alert(s) match patched lock entries"
    return fixed, summary


def _read_feed(
    path: str, label: str, row_builder: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str]:
    alerts, note = _get(path)
    if alerts is None:
        return [], f"{label}: {note}"
    return row_builder(alerts), ""


def collect() -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    notes: list[str] = []
    ref = code_scanning_ref()
    code_path = "/code-scanning/alerts?state=open&per_page=100"
    if ref:
        code_path += f"&ref={urllib.parse.quote(ref, safe='/')}"
        notes.append(f"code scanning scoped to {ref}")
    feeds = (
        (code_path, "code scanning", lambda rows: [_code_row(row) for row in rows]),
        ("/dependabot/alerts?state=open&per_page=100", "dependabot",
         lambda rows: [_dependabot_row(row) for row in rows]),
        ("/secret-scanning/alerts?state=open&per_page=100", "secret scanning",
         _scanning_rows),
    )
    for path, label, row_builder in feeds:
        rows, note = _read_feed(path, label, row_builder)
        if label == "dependabot" and not note:
            fixed, comparison_note = _fixed_dependabot_alerts_by_pr(rows)
            for row in rows:
                row["fixed_by_pr"] = str(row.get("number")) in fixed
            if comparison_note:
                notes.append(comparison_note)
        findings.extend(rows)
        if note:
            notes.append(note)
    return findings, notes


def _note_is_missing(note: str) -> bool:
    return ("no GITHUB_TOKEN" in note or "no SECRET_SCANNING_TOKEN" in note)


def _note_is_read_failure(note: str, strict: bool) -> bool:
    """PR scope is metadata; missing fork secrets are an explicit skip."""
    if note.startswith(("code scanning scoped to ",
                        "dependabot PR fixes checked: ",
                        "dependabot PR comparison unavailable: ")):
        return False
    if "no SECRET_SCANNING_TOKEN" in note and _is_fork_pull_request():
        return False
    return strict if _note_is_missing(note) else True


def _feed_read_failed(notes: list[str], strict: bool) -> bool:
    """Distinguish informational PR scope from unreadable feeds."""
    return any(_note_is_read_failure(note, strict) for note in notes)


def _note_kind(note: str) -> str:
    """Classify scope, local credential skips, and actual feed errors."""
    if note.startswith(("code scanning scoped to ",
                        "dependabot PR fixes checked: ",
                        "dependabot PR comparison unavailable: ")):
        return "INFO"
    if _note_is_missing(note):
        return "SKIPPED"
    return "ERROR"


def _print_notes(notes: list[str]) -> None:
    """Keep read-scope information distinct from missing/unreadable feeds."""
    for note in notes:
        print(f"security alerts: {_note_kind(note)} -- {note}")


def _parse_args(argv: list[str]) -> tuple[str | None, bool]:
    threshold = None
    for i, arg in enumerate(argv):
        if arg == "--max-severity" and i + 1 < len(argv):
            threshold = argv[i + 1]
        elif arg.startswith("--max-severity="):
            threshold = arg.split("=", 1)[1]
    return threshold, "--require-readable-feeds" in argv


def _print_findings(findings: list[dict[str, Any]]) -> None:
    by_feed: dict[str, int] = {}
    for finding in findings:
        by_feed[finding["feed"]] = by_feed.get(finding["feed"], 0) + 1
    summary = ", ".join(f"{count} {feed}" for feed, count in sorted(by_feed.items()))
    print(f"security alerts: {len(findings)} open ({summary})")
    ordered = sorted(findings, key=lambda item: -_rank(item["severity"]))
    for finding in ordered:
        print(f"  #{finding['number']} [{finding['severity']}] "
              f"{finding['id']}  {finding['where']}")


def _threshold_exit(
    findings: list[dict[str, Any]], threshold: str | None, *, scoped_pr: bool,
) -> int:
    if not threshold:
        return 0
    # Dependabot's repository endpoint reports the default-branch manifest,
    # not the PR's proposed lock. Ignore only an alert whose exact manifest
    # and package this PR updates to the first patched version; unrelated or
    # ambiguous findings continue to block. Push runs always check every feed.
    candidates = [item for item in findings
                  if not (scoped_pr and item["feed"] == "dependabot"
                          and item.get("fixed_by_pr"))]
    over = [item for item in candidates
            if _rank(item["severity"]) >= _rank(threshold)]
    if not over:
        print(f"  none at or above '{threshold}'.")
        return 0
    print()
    print(f"  {len(over)} at or above '{threshold}' -- these block the build.")
    return 1


def main(argv: list[str]) -> int:
    threshold, strict = _parse_args(argv)
    findings, notes = collect()
    _print_notes(notes)
    if _feed_read_failed(notes, strict):
        # Partial visibility must never be mistaken for a clean result.
        print("security alerts: ERROR -- one or more feeds could not be read")
        return 2
    if any(_note_is_missing(note) for note in notes) and not findings:
        # Local invocation without a token: explicit skip, not a clean claim.
        return 0
    if not findings:
        print("security alerts: OK (no open alerts in any feed)")
        return 0
    _print_findings(findings)
    scoped_pr = code_scanning_ref() is not None
    return _threshold_exit(findings, threshold, scoped_pr=scoped_pr)
