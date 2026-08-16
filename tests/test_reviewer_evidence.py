"""Exact-head reviewer evidence must never bless stale or malformed surfaces."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.governance.reviewer_evidence import (  # noqa: E402
    EvidenceError,
    collect_github_evidence,
    summarize_evidence,
)

HEAD = "a" * 40
OLD = "b" * 40
NEW = "c" * 40
CORPUS = Path(__file__).resolve().parents[1] / "integrations" / "reviewer_benchmark_corpus.json"


def _pr(sha: str = HEAD) -> dict:
    return {"head": {"sha": sha}}


def _bound(actor: str, commit_id=HEAD, **extra) -> dict:
    return {
        "user": {"login": actor},
        "commit_id": commit_id,
        "state": extra.get("state", "COMMENTED"),
        "html_url": f"https://example.test/{actor}",
    }


def _ordinary(actor: str) -> dict:
    return {
        "user": {"login": actor},
        "created_at": "2026-08-16T00:00:00Z",
        "html_url": f"https://example.test/{actor}/ordinary",
    }


def _check(name: str, check_id: int, conclusion: str = "success") -> dict:
    return {
        "name": name,
        "id": check_id,
        "status": "completed",
        "conclusion": conclusion,
        "details_url": f"https://example.test/check/{check_id}",
    }


def _summary(**overrides):
    values = {
        "pr_before": _pr(),
        "pr_after": _pr(),
        "reviews": [],
        "review_comments": [],
        "ordinary_comments": [],
        "check_runs": [],
    }
    values.update(overrides)
    return summarize_evidence(**values)


def test_benchmark_corpus_is_safe_unique_and_never_mergeable():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert corpus["schema_version"] == 1
    assert corpus["merge_policy"] == "never"
    assert corpus["safety"] == {
        "credential_shaped_literals": False,
        "live_exploit_execution": False,
        "workflow_secrets": False,
        "pull_request_target": False,
        "required_check": False,
    }
    cases = corpus["defect_cases"] + corpus["benign_controls"]
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert len(corpus["defect_cases"]) >= 7
    assert len(corpus["benign_controls"]) >= 4
    assert {
        "tool", "exact_head", "ran", "status", "quota_state",
        "findings_total", "accepted", "false_positives", "permissions",
        "cost", "failure_mode",
    } <= set(corpus["result_fields"])


def test_summary_separates_exact_stale_and_unbound_surfaces():
    evidence = _summary(
        reviews=[
            _bound("exact-reviewer"),
            _bound("stale-reviewer", OLD),
            _bound("unbound-reviewer", None),
        ],
        review_comments=[
            _bound("exact-reviewer"),
            _bound("stale-reviewer", OLD),
        ],
        ordinary_comments=[_ordinary("guide-bot")],
        check_runs=[_check("DeepSource: Analysis", 1, "skipped")],
    )
    assert evidence["head_sha"] == HEAD
    assert evidence["head_stable"] is True
    assert evidence["summary"] == {
        "exact_bound_items": 2,
        "stale_bound_items": 2,
        "unbound_items": 2,
        "checks": 1,
    }
    assert evidence["schema_version"] == 1
    assert evidence["actors"] == {
        "exact-reviewer": {
            "exact_reviews": 1, "stale_reviews": 0, "unbound_reviews": 0,
            "exact_inline_comments": 1, "stale_inline_comments": 0,
            "unbound_inline_comments": 0, "ordinary_comments": 0,
        },
        "guide-bot": {
            "exact_reviews": 0, "stale_reviews": 0, "unbound_reviews": 0,
            "exact_inline_comments": 0, "stale_inline_comments": 0,
            "unbound_inline_comments": 0, "ordinary_comments": 1,
        },
        "stale-reviewer": {
            "exact_reviews": 0, "stale_reviews": 1, "unbound_reviews": 0,
            "exact_inline_comments": 0, "stale_inline_comments": 1,
            "unbound_inline_comments": 0, "ordinary_comments": 0,
        },
        "unbound-reviewer": {
            "exact_reviews": 0, "stale_reviews": 0, "unbound_reviews": 1,
            "exact_inline_comments": 0, "stale_inline_comments": 0,
            "unbound_inline_comments": 0, "ordinary_comments": 0,
        },
    }
    assert evidence["surfaces"]["submitted_reviews"] == [
        {"actor": "exact-reviewer", "binding": "exact", "commit_id": HEAD,
         "state": "COMMENTED", "html_url": "https://example.test/exact-reviewer"},
        {"actor": "stale-reviewer", "binding": "stale", "commit_id": OLD,
         "state": "COMMENTED", "html_url": "https://example.test/stale-reviewer"},
        {"actor": "unbound-reviewer", "binding": "unbound", "commit_id": None,
         "state": "COMMENTED", "html_url": "https://example.test/unbound-reviewer"},
    ]
    assert evidence["surfaces"]["inline_comments"] == [
        {"actor": "exact-reviewer", "binding": "exact", "commit_id": HEAD,
         "state": "COMMENTED", "html_url": "https://example.test/exact-reviewer"},
        {"actor": "stale-reviewer", "binding": "stale", "commit_id": OLD,
         "state": "COMMENTED", "html_url": "https://example.test/stale-reviewer"},
    ]
    assert evidence["surfaces"]["ordinary_comments"] == [{
        "actor": "guide-bot", "binding": "unbound",
        "created_at": "2026-08-16T00:00:00Z",
        "html_url": "https://example.test/guide-bot/ordinary",
    }]
    assert evidence["surfaces"]["check_runs"] == [{
        "name": "DeepSource: Analysis", "id": 1, "head_sha": HEAD,
        "status": "completed", "conclusion": "skipped",
        "details_url": "https://example.test/check/1",
    }]


def test_expected_head_mismatch_fails_closed():
    with pytest.raises(EvidenceError) as raised:
        _summary(expected_head=OLD)
    assert str(raised.value) == (
        f"expected head {OLD!r} does not match PR head {HEAD!r}"
    )


def test_head_change_during_collection_fails_closed():
    with pytest.raises(EvidenceError) as raised:
        _summary(pr_after=_pr(NEW))
    assert str(raised.value) == (
        f"pull request head changed during collection: {HEAD} -> {NEW}"
    )


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("pr_before", [], "pull request must be a JSON object"),
        ("pr_before", {"head": []}, "pull request head must be a JSON object"),
        ("pr_before", {"head": {"sha": "ABC"}},
         "pull request head sha must be 40 lowercase hex characters"),
        ("reviews", {}, "submitted reviews must be a JSON array"),
        ("review_comments", {}, "inline comments must be a JSON array"),
        ("ordinary_comments", {}, "ordinary comments must be a JSON array"),
        ("check_runs", {}, "check runs must be a JSON array"),
    ],
)
def test_malformed_root_shapes_fail_closed(field, value, message):
    with pytest.raises(EvidenceError) as raised:
        _summary(**{field: value})
    assert str(raised.value) == message


def test_malformed_actor_and_commit_binding_fail_closed():
    with pytest.raises(EvidenceError) as raised:
        _summary(reviews=[{"user": [], "commit_id": HEAD}])
    assert str(raised.value) == (
        "submitted reviews[0] user must be a JSON object"
    )
    with pytest.raises(EvidenceError) as raised:
        _summary(ordinary_comments=[{"user": []}])
    assert str(raised.value) == (
        "ordinary comments[0] user must be a JSON object"
    )
    with pytest.raises(EvidenceError) as raised:
        _summary(reviews=[{"user": {}, "commit_id": HEAD}])
    assert str(raised.value) == (
        "submitted reviews[0] user login must be a non-empty string"
    )
    with pytest.raises(EvidenceError) as raised:
        _summary(reviews=[_bound("bot", "not-a-sha")])
    assert str(raised.value) == (
        "submitted reviews[0] commit_id must be null or 40 lowercase hex"
    )


def test_malformed_member_rows_fail_closed_with_surface_index():
    with pytest.raises(EvidenceError) as raised:
        _summary(reviews=[[]])
    assert str(raised.value) == "submitted reviews[0] must be a JSON object"
    with pytest.raises(EvidenceError) as raised:
        _summary(ordinary_comments=[[]])
    assert str(raised.value) == "ordinary comments[0] must be a JSON object"
    with pytest.raises(EvidenceError) as raised:
        _summary(check_runs=[[]])
    assert str(raised.value) == "check runs[0] must be a JSON object"


def test_malformed_and_duplicate_check_records_fail_closed():
    with pytest.raises(EvidenceError) as raised:
        _summary(check_runs=[{"name": "", "id": 1}])
    assert str(raised.value) == "check runs[0] name must be a non-empty string"
    with pytest.raises(EvidenceError) as raised:
        _summary(check_runs=[{"name": "CI", "id": "1"}])
    assert str(raised.value) == "check runs[0] id must be an integer"
    with pytest.raises(EvidenceError) as raised:
        _summary(check_runs=[_check("CI", 1), _check("Security", 1)])
    assert str(raised.value) == "duplicate check evidence: Security id=1"


def test_repeated_rows_accumulate_per_actor_and_binding():
    evidence = _summary(
        reviews=[_bound("bot"), _bound("bot")],
        review_comments=[_bound("bot", None), _bound("bot", None)],
        ordinary_comments=[_ordinary("bot"), _ordinary("bot")],
    )
    actor = evidence["actors"]["bot"]
    assert actor["exact_reviews"] == 2
    assert actor["unbound_inline_comments"] == 2
    assert actor["ordinary_comments"] == 2
    assert evidence["summary"]["exact_bound_items"] == 2
    assert evidence["summary"]["unbound_items"] == 4


def test_actor_rows_start_with_every_counter_at_zero():
    evidence = _summary(ordinary_comments=[_ordinary("bot")])
    assert evidence["actors"]["bot"] == {
        "exact_reviews": 0,
        "stale_reviews": 0,
        "unbound_reviews": 0,
        "exact_inline_comments": 0,
        "stale_inline_comments": 0,
        "unbound_inline_comments": 0,
        "ordinary_comments": 1,
    }


def test_collect_fetches_checks_for_the_observed_head_and_rechecks_pr():
    paths: list[str] = []
    responses = {
        "/repos/owner/repo/pulls/7": [_pr(), _pr()],
        "/repos/owner/repo/pulls/7/reviews?per_page=100": [[]],
        "/repos/owner/repo/pulls/7/comments?per_page=100": [[]],
        "/repos/owner/repo/issues/7/comments?per_page=100": [[]],
        f"/repos/owner/repo/commits/{HEAD}/check-runs?per_page=100": [
            {"total_count": 1, "check_runs": [_check("CI", 9)]}
        ],
    }

    def fetch(path: str):
        paths.append(path)
        return responses[path].pop(0)

    evidence = collect_github_evidence(
        repo="owner/repo", pr_number=7, fetch_json=fetch, expected_head=HEAD,
    )
    assert evidence["summary"]["checks"] == 1
    assert paths == [
        "/repos/owner/repo/pulls/7",
        "/repos/owner/repo/pulls/7/reviews?per_page=100",
        "/repos/owner/repo/pulls/7/comments?per_page=100",
        "/repos/owner/repo/issues/7/comments?per_page=100",
        f"/repos/owner/repo/commits/{HEAD}/check-runs?per_page=100",
        "/repos/owner/repo/pulls/7",
    ]


@pytest.mark.parametrize("repo", ["owner", "owner/repo/extra", "owner/re po", "/repo"])
def test_collect_rejects_invalid_repository_shape(repo):
    with pytest.raises(EvidenceError) as raised:
        collect_github_evidence(repo=repo, pr_number=1, fetch_json=lambda _path: {})
    assert str(raised.value) == "repo must have owner/name form"


@pytest.mark.parametrize("number", [0, -1, True, "1"])
def test_collect_rejects_invalid_pr_number(number):
    with pytest.raises(EvidenceError) as raised:
        collect_github_evidence(
            repo="owner/repo", pr_number=number, fetch_json=lambda _path: {},
        )
    assert str(raised.value) == "pr_number must be a positive integer"


def test_collect_rejects_malformed_check_response_shape():
    responses = iter([_pr(), [], [], [], [], _pr()])
    with pytest.raises(EvidenceError) as raised:
        collect_github_evidence(
            repo="owner/repo", pr_number=1, fetch_json=lambda _path: next(responses),
        )
    assert str(raised.value) == "check-runs response must be a JSON object"

    responses = iter([_pr(), [], [], [], {"total_count": 0}, _pr()])
    with pytest.raises(EvidenceError) as raised:
        collect_github_evidence(
            repo="owner/repo", pr_number=1, fetch_json=lambda _path: next(responses),
        )
    assert str(raised.value) == "check runs must be a JSON array"


def test_collect_rejects_missing_or_truncated_check_count():
    responses = iter([
        _pr(), [], [], [], {"total_count": 2, "check_runs": [_check("CI", 1)]}, _pr(),
    ])
    with pytest.raises(EvidenceError) as raised:
        collect_github_evidence(
            repo="owner/repo", pr_number=1, fetch_json=lambda _path: next(responses),
        )
    assert str(raised.value) == (
        "check-runs response total_count must exactly match collected check_runs"
    )
