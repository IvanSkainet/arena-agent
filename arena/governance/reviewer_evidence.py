"""Fail-closed exact-head evidence model for GitHub PR reviewer surfaces."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class EvidenceError(ValueError):
    """Reviewer evidence is malformed, stale at collection, or wrong-head."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be a JSON object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvidenceError(f"{label} must be a JSON array")
    return value


def _head_sha(pr: Any) -> str:
    obj = _object(pr, "pull request")
    head = _object(obj.get("head"), "pull request head")
    sha = head.get("sha")
    if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
        raise EvidenceError("pull request head sha must be 40 lowercase hex characters")
    return sha


def _actor(row: dict[str, Any], label: str) -> str:
    user = _object(row.get("user"), f"{label} user")
    login = user.get("login")
    if not isinstance(login, str) or not login.strip():
        raise EvidenceError(f"{label} user login must be a non-empty string")
    return login


def _bound_surface(
    rows: Any,
    *,
    label: str,
    head_sha: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    output: list[dict[str, Any]] = []
    actors: dict[str, dict[str, int]] = defaultdict(
        lambda: {"exact": 0, "stale": 0, "unbound": 0}
    )
    for index, raw in enumerate(_array(rows, label)):
        row = _object(raw, f"{label}[{index}]")
        actor = _actor(row, f"{label}[{index}]")
        commit_id = row.get("commit_id")
        if commit_id is None:
            binding = "unbound"
        elif not isinstance(commit_id, str) or not _SHA_RE.fullmatch(commit_id):
            raise EvidenceError(f"{label}[{index}] commit_id must be null or 40 lowercase hex")
        else:
            binding = "exact" if commit_id == head_sha else "stale"
        actors[actor][binding] += 1
        output.append({
            "actor": actor,
            "binding": binding,
            "commit_id": commit_id,
            "state": row.get("state"),
            "html_url": row.get("html_url"),
        })
    return output, dict(actors)


def _ordinary_comments(rows: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    output: list[dict[str, Any]] = []
    actors: dict[str, int] = defaultdict(int)
    for index, raw in enumerate(_array(rows, "ordinary comments")):
        row = _object(raw, f"ordinary comments[{index}]")
        actor = _actor(row, f"ordinary comments[{index}]")
        actors[actor] += 1
        output.append({
            "actor": actor,
            "binding": "unbound",
            "created_at": row.get("created_at"),
            "html_url": row.get("html_url"),
        })
    return output, dict(actors)


def _checks(rows: Any, head_sha: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, raw in enumerate(_array(rows, "check runs")):
        row = _object(raw, f"check runs[{index}]")
        name = row.get("name")
        check_id = row.get("id")
        if not isinstance(name, str) or not name.strip():
            raise EvidenceError(f"check runs[{index}] name must be a non-empty string")
        if not isinstance(check_id, int):
            raise EvidenceError(f"check runs[{index}] id must be an integer")
        if check_id in seen_ids:
            raise EvidenceError(f"duplicate check evidence: {name} id={check_id}")
        seen_ids.add(check_id)
        output.append({
            "name": name,
            "id": check_id,
            "head_sha": head_sha,
            "status": row.get("status"),
            "conclusion": row.get("conclusion"),
            "details_url": row.get("details_url"),
        })
    return output


def summarize_evidence(
    *,
    pr_before: Any,
    pr_after: Any,
    reviews: Any,
    review_comments: Any,
    ordinary_comments: Any,
    check_runs: Any,
    expected_head: str | None = None,
) -> dict[str, Any]:
    """Summarize all PR review surfaces without treating stale data as signal."""
    head_before = _head_sha(pr_before)
    head_after = _head_sha(pr_after)
    if expected_head is not None and expected_head != head_before:
        raise EvidenceError(
            f"expected head {expected_head!r} does not match PR head {head_before!r}"
        )
    if head_after != head_before:
        raise EvidenceError(
            f"pull request head changed during collection: {head_before} -> {head_after}"
        )

    submitted, submitted_actors = _bound_surface(
        reviews, label="submitted reviews", head_sha=head_before,
    )
    inline, inline_actors = _bound_surface(
        review_comments, label="inline comments", head_sha=head_before,
    )
    ordinary, ordinary_actors = _ordinary_comments(ordinary_comments)
    checks = _checks(check_runs, head_before)

    actors: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "exact_reviews": 0,
            "stale_reviews": 0,
            "unbound_reviews": 0,
            "exact_inline_comments": 0,
            "stale_inline_comments": 0,
            "unbound_inline_comments": 0,
            "ordinary_comments": 0,
        }
    )
    for actor, counts in submitted_actors.items():
        actors[actor]["exact_reviews"] = counts["exact"]
        actors[actor]["stale_reviews"] = counts["stale"]
        actors[actor]["unbound_reviews"] = counts["unbound"]
    for actor, counts in inline_actors.items():
        actors[actor]["exact_inline_comments"] = counts["exact"]
        actors[actor]["stale_inline_comments"] = counts["stale"]
        actors[actor]["unbound_inline_comments"] = counts["unbound"]
    for actor, count in ordinary_actors.items():
        actors[actor]["ordinary_comments"] = count

    return {
        "schema_version": 1,
        "head_sha": head_before,
        "head_stable": True,
        "surfaces": {
            "submitted_reviews": submitted,
            "inline_comments": inline,
            "ordinary_comments": ordinary,
            "check_runs": checks,
        },
        "actors": dict(sorted(actors.items())),
        "summary": {
            "exact_bound_items": sum(
                row["binding"] == "exact" for row in submitted + inline
            ),
            "stale_bound_items": sum(
                row["binding"] == "stale" for row in submitted + inline
            ),
            "unbound_items": (
                sum(row["binding"] == "unbound" for row in submitted + inline)
                + len(ordinary)
            ),
            "checks": len(checks),
        },
    }


def collect_github_evidence(
    *,
    repo: str,
    pr_number: int,
    fetch_json: Callable[[str], Any],
    expected_head: str | None = None,
) -> dict[str, Any]:
    """Fetch exact-head GitHub surfaces, detecting a head change during reads."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise EvidenceError("repo must have owner/name form")
    if type(pr_number) is not int or pr_number <= 0:
        raise EvidenceError("pr_number must be a positive integer")
    prefix = f"/repos/{repo}"
    pr_before = fetch_json(f"{prefix}/pulls/{pr_number}")
    head = _head_sha(pr_before)
    reviews = fetch_json(f"{prefix}/pulls/{pr_number}/reviews?per_page=100")
    review_comments = fetch_json(f"{prefix}/pulls/{pr_number}/comments?per_page=100")
    ordinary_comments = fetch_json(f"{prefix}/issues/{pr_number}/comments?per_page=100")
    check_doc = _object(
        fetch_json(f"{prefix}/commits/{head}/check-runs?per_page=100"),
        "check-runs response",
    )
    check_runs = _array(check_doc.get("check_runs"), "check runs")
    total_count = check_doc.get("total_count")
    if not isinstance(total_count, int) or total_count != len(check_runs):
        raise EvidenceError(
            "check-runs response total_count must exactly match collected check_runs"
        )
    pr_after = fetch_json(f"{prefix}/pulls/{pr_number}")
    return summarize_evidence(
        pr_before=pr_before,
        pr_after=pr_after,
        reviews=reviews,
        review_comments=review_comments,
        ordinary_comments=ordinary_comments,
        check_runs=check_runs,
        expected_head=expected_head,
    )


__all__ = ["EvidenceError", "collect_github_evidence", "summarize_evidence"]
