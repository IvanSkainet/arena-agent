"""Evidence-checked credit for reviewed, unpublished intermediate patch tags."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from release_version_contract import release_tag_parts

LEDGER = Path(__file__).resolve().parents[1] / "docs/audits/release-withdrawals.json"
Fetch = Callable[[str], Any]
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _records() -> list[dict]:
    if not LEDGER.exists():
        return []
    value = json.loads(LEDGER.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("invalid release withdrawal ledger schema")
    entries = value.get("withdrawals")
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        raise ValueError("withdrawals must be an array of records")
    tags = [e.get("tag") for e in entries]
    if any(not isinstance(t, str) for t in tags) or len(set(tags)) != len(tags):
        raise ValueError("withdrawal tags must be unique strings")
    return entries


def _validated_record(entry: dict, repo: str) -> None:
    if not release_tag_parts(str(entry.get("tag", ""))):
        raise ValueError("withdrawal tag is not a strict release version")
    for key in ("tag_object", "source_commit"):
        if not isinstance(entry.get(key), str) or not _SHA.fullmatch(entry[key]):
            raise ValueError(f"withdrawal {key} is not a commit/object digest")
    for key in ("deleted_draft_id", "failed_signing_run"):
        if type(entry.get(key)) is not int or entry[key] <= 0:
            raise ValueError(f"withdrawal {key} must be a positive integer")
    if entry.get("repository") != repo or not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
        raise ValueError("withdrawal needs the current repository and a reason")
    if entry.get("was_draft") is not True:
        raise ValueError("only a recorded unpublished draft can be withdrawn")


def _object_matches(value: Any, sha: str, kind: str) -> bool:
    obj = value.get("object") if isinstance(value, dict) else None
    return isinstance(obj, dict) and obj.get("sha") == sha and obj.get("type") == kind


def _verify_tag(entry: dict, fetch: Fetch) -> None:
    ref = fetch("/git/ref/tags/" + entry["tag"])
    if not _object_matches(ref, entry["tag_object"], "tag"):
        raise ValueError("withdrawn annotated tag reference changed or is unavailable")
    tag = fetch("/git/tags/" + entry["tag_object"])
    if not isinstance(tag, dict) or tag.get("tag") != entry["tag"]:
        raise ValueError("withdrawn tag object is unavailable or mismatched")
    if not _object_matches(tag, entry["source_commit"], "commit"):
        raise ValueError("withdrawn tag no longer identifies the recorded source")


def _verify_failed_signer(entry: dict, fetch: Fetch) -> None:
    run = fetch("/actions/runs/" + str(entry["failed_signing_run"]))
    expected = {
        "id": entry["failed_signing_run"], "head_sha": entry["source_commit"],
        "path": ".github/workflows/sign-release.yml", "event": "workflow_dispatch",
        "status": "completed", "conclusion": "failure",
    }
    if not isinstance(run, dict) or any(run.get(k) != v for k, v in expected.items()):
        raise ValueError("withdrawal signing failure evidence does not match")
    repository = run.get("repository")
    if not isinstance(repository, dict) or repository.get("full_name") != entry["repository"]:
        raise ValueError("withdrawal signing evidence belongs to another repository")


def _verify_no_release(entry: dict, fetch: Fetch) -> None:
    # By-tag alone excludes drafts. Also prove the recorded draft is gone,
    # and enumerate all releases (including drafts visible to the CI token).
    for endpoint in ("/releases/" + str(entry["deleted_draft_id"]), "/releases/tags/" + entry["tag"]):
        if fetch(endpoint) != {}:
            raise ValueError("withdrawn release still exists or absence is unproven")
    for page in range(1, 21):
        releases = fetch(f"/releases?per_page=100&page={page}")
        if not isinstance(releases, list) or any(not isinstance(r, dict) or not isinstance(r.get("tag_name"), str) for r in releases):
            raise ValueError("cannot enumerate releases to verify withdrawal")
        if any(r["tag_name"] == entry["tag"] for r in releases):
            raise ValueError("withdrawn tag has a draft or published release")
        if len(releases) < 100:
            return
    raise ValueError("release enumeration incomplete; withdrawal is unproven")


def withdrawal_credit(tree: tuple, published: tuple, fetch: Fetch, repo: str) -> int:
    """Deduct only verified intermediate patches, never the active version."""
    if tree[:2] != published[:2]:
        return 0
    credit = 0
    for entry in _records():
        _validated_record(entry, repo)
        version = release_tag_parts(entry["tag"])
        if version[:2] != tree[:2] or not published < version < tree:
            continue
        _verify_tag(entry, fetch)
        _verify_failed_signer(entry, fetch)
        _verify_no_release(entry, fetch)
        print(f"  verified withdrawn unpublished patch: {entry['tag']}")
        credit += 1
    return credit
