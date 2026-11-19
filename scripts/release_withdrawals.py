"""Evidence-checked credit for reviewed, unpublished intermediate patch tags."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from release_version_contract import release_tag_parts

LEDGER = Path(__file__).resolve().parents[1] / "docs/audits/release-withdrawals.json"
Fetch = Callable[[str], Any]
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _object(value: Any, label: str) -> dict:
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    _require(isinstance(value, str), f"{label} must be a string")
    _require(bool(value.strip()), f"{label} must not be empty")
    return value


def _digest(value: Any, label: str) -> None:
    text = _text(value, label)
    _require(bool(_SHA.fullmatch(text)), f"{label} must be an object digest")


def _positive_integer(value: Any, label: str) -> None:
    _require(type(value) is int, f"{label} must be an integer")
    _require(value > 0, f"{label} must be positive")


def _object_list(value: Any, label: str) -> list[dict]:
    _require(isinstance(value, list), f"{label} must be an array")
    return [_object(item, label) for item in value]


def _unique_tags(entries: list[dict]) -> None:
    tags = [_text(entry.get("tag"), "withdrawal tag") for entry in entries]
    _require(len(set(tags)) == len(tags), "withdrawal tags must be unique")


def _records() -> list[dict]:
    if not LEDGER.exists():
        return []
    value = _object(json.loads(LEDGER.read_text(encoding="utf-8")), "ledger")
    _positive_integer(value.get("schema_version"), "ledger schema version")
    _require(value["schema_version"] == 1, "invalid withdrawal ledger schema")
    entries = _object_list(value.get("withdrawals"), "withdrawals")
    _unique_tags(entries)
    return entries


def _validated_record(entry: dict, repo: str) -> None:
    tag = _text(entry.get("tag"), "withdrawal tag")
    _require(bool(release_tag_parts(tag)), "withdrawal tag is not a strict version")
    _digest(entry.get("tag_object"), "tag object")
    _digest(entry.get("source_commit"), "source commit")
    _positive_integer(entry.get("deleted_draft_id"), "deleted draft ID")
    _positive_integer(entry.get("failed_signing_run"), "failed signing run")
    _require(entry.get("repository") == repo, "withdrawal repository mismatch")
    _text(entry.get("reason"), "withdrawal reason")
    _require(entry.get("was_draft") is True, "only an unpublished draft can be withdrawn")


def _expect_fields(value: Any, expected: dict, label: str) -> dict:
    obj = _object(value, label)
    for key, required in expected.items():
        _require(obj.get(key) == required, f"{label}: mismatched {key}")
    return obj


def _expect_git_target(value: dict, sha: str, kind: str) -> None:
    _expect_fields(value.get("object"), {"sha": sha, "type": kind}, "Git target")


def _verify_tag(entry: dict, fetch: Fetch) -> None:
    ref = _object(fetch("/git/ref/tags/" + entry["tag"]), "tag reference")
    _expect_git_target(ref, entry["tag_object"], "tag")
    tag = _expect_fields(fetch("/git/tags/" + entry["tag_object"]), {"tag": entry["tag"]}, "annotated tag")
    _expect_git_target(tag, entry["source_commit"], "commit")


def _verify_failed_signer(entry: dict, fetch: Fetch) -> None:
    expected = {
        "id": entry["failed_signing_run"], "head_sha": entry["source_commit"],
        "path": ".github/workflows/sign-release.yml", "event": "workflow_dispatch",
        "status": "completed", "conclusion": "failure",
    }
    run = _expect_fields(fetch("/actions/runs/" + str(entry["failed_signing_run"])), expected, "failed signer")
    _expect_fields(run.get("repository"), {"full_name": entry["repository"]}, "signer repository")


def _verify_deleted_release(entry: dict, fetch: Fetch) -> None:
    endpoints = (
        "/releases/" + str(entry["deleted_draft_id"]),
        "/releases/tags/" + entry["tag"],
    )
    for endpoint in endpoints:
        _require(fetch(endpoint) == {}, "withdrawn release still exists or absence is unproven")


def _release_page(value: Any, tag: str) -> list[dict]:
    releases = _object_list(value, "release enumeration")
    tags = [_text(release.get("tag_name"), "release tag") for release in releases]
    _require(tag not in tags, "withdrawn tag has a draft or published release")
    return releases


def _verify_no_release(entry: dict, fetch: Fetch) -> None:
    # By-tag alone excludes drafts. Prove the old draft was removed and
    # enumerate releases, including drafts visible to the CI token.
    _verify_deleted_release(entry, fetch)
    for page in range(1, 21):
        releases = _release_page(fetch(f"/releases?per_page=100&page={page}"), entry["tag"])
        if len(releases) < 100:
            return
    raise ValueError("release enumeration incomplete; withdrawal is unproven")


def _intermediate_patch(entry: dict, tree: tuple, published: tuple) -> bool:
    version = release_tag_parts(entry["tag"])
    return version[:2] == tree[:2] and published < version < tree


def _verify_withdrawal(entry: dict, fetch: Fetch) -> None:
    _verify_tag(entry, fetch)
    _verify_failed_signer(entry, fetch)
    _verify_no_release(entry, fetch)
    print(f"  verified withdrawn unpublished patch: {entry['tag']}")


def withdrawal_credit(tree: tuple, published: tuple, fetch: Fetch, repo: str) -> int:
    """Deduct only verified intermediate patches, never the active version."""
    if tree[:2] != published[:2]:
        return 0
    credit = 0
    for entry in _records():
        _validated_record(entry, repo)
        if _intermediate_patch(entry, tree, published):
            _verify_withdrawal(entry, fetch)
            credit += 1
    return credit
