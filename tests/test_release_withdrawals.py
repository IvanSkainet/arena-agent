"""Withdrawn-version credit must be proven and cannot hide release debt."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release_withdrawals as withdrawals  # noqa: E402 -- scripts path bootstrap.


@pytest.fixture()
def evidence(monkeypatch, tmp_path):
    ledger = json.loads((ROOT / "docs/audits/release-withdrawals.json").read_text())
    entry = ledger["withdrawals"][0]
    path = tmp_path / "withdrawals.json"
    path.write_text(json.dumps(ledger))
    monkeypatch.setattr(withdrawals, "LEDGER", path)
    tag = entry["tag"]
    rows = {
        "/releases/latest": {"tag_name": "v4.170.0", "assets": [{"name": "arena-agent.zip"}]},
        "/git/ref/tags/" + tag: {"object": {"sha": entry["tag_object"], "type": "tag"}},
        "/git/tags/" + entry["tag_object"]: {"tag": tag, "object": {"sha": entry["source_commit"], "type": "commit"}},
        "/actions/runs/" + str(entry["failed_signing_run"]): {
            "id": entry["failed_signing_run"], "head_sha": entry["source_commit"],
            "path": ".github/workflows/sign-release.yml", "event": "workflow_dispatch",
            "status": "completed", "conclusion": "failure", "repository": {"full_name": entry["repository"]},
        },
        "/releases/" + str(entry["deleted_draft_id"]): {},
        "/releases/tags/" + tag: {},
        "/releases?per_page=100&page=1": [],
    }
    spec = importlib.util.spec_from_file_location("withdrawal_gate_probe", ROOT / "scripts/release_published_check.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    monkeypatch.setattr(gate, "current_version", lambda: "4.170.2")
    monkeypatch.setattr(gate, "_api", lambda endpoint: copy.deepcopy(rows[endpoint]))
    return gate, rows, entry


def test_verified_intermediate_withdrawal_keeps_one_patch_limit(evidence):
    gate, _, _ = evidence
    assert gate.main([]) == 0  # nosec B101 -- pytest regression oracle, not runtime authorization.
    assert gate.main(["--strict"]) == 1  # nosec B101 -- pytest regression oracle, not runtime authorization.


def test_two_real_unpublished_patches_still_fail(evidence, monkeypatch):
    gate, _, _ = evidence
    monkeypatch.setattr(gate, "current_version", lambda: "4.170.3")
    assert gate.main([]) == 1  # nosec B101 -- pytest regression oracle, not runtime authorization.


def test_active_or_published_patch_cannot_receive_credit(evidence):
    gate, _, entry = evidence
    fetch = gate._api
    repo = entry["repository"]
    assert withdrawals.withdrawal_credit((4, 170, 1), (4, 170, 0), fetch, repo) == 0  # nosec B101 -- pytest regression oracle, not runtime authorization.
    assert withdrawals.withdrawal_credit((4, 170, 2), (4, 170, 1), fetch, repo) == 0  # nosec B101 -- pytest regression oracle, not runtime authorization.
    assert withdrawals.withdrawal_credit((4, 171, 0), (4, 170, 0), fetch, repo) == 0  # nosec B101 -- pytest regression oracle, not runtime authorization.


@pytest.mark.parametrize("kind", ["tag_ref", "tag_source", "run_source", "run_workflow", "run_success", "run_repo", "draft_exists", "public_exists", "new_draft", "no_answer", "invalid_listing"])
def test_unproven_withdrawal_fails_closed(evidence, kind):
    gate, rows, entry = evidence
    changes = {
        "tag_ref": ("/git/ref/tags/" + entry["tag"], {"object": {"sha": "0" * 40, "type": "tag"}}),
        "tag_source": ("/git/tags/" + entry["tag_object"], {}),
        "draft_exists": ("/releases/" + str(entry["deleted_draft_id"]), {"draft": True}),
        "public_exists": ("/releases/tags/" + entry["tag"], {"draft": False}),
        "new_draft": ("/releases?per_page=100&page=1", [{"tag_name": entry["tag"], "draft": True}]),
        "no_answer": ("/releases?per_page=100&page=1", None),
        "invalid_listing": ("/releases?per_page=100&page=1", [{}]),
    }
    if kind in changes:
        endpoint, value = changes[kind]
        rows[endpoint] = value
    else:
        run = rows["/actions/runs/" + str(entry["failed_signing_run"])]
        key, value = {
            "run_source": ("head_sha", "0" * 40),
            "run_workflow": ("path", ".github/workflows/other.yml"),
            "run_success": ("conclusion", "success"),
            "run_repo": ("repository", {"full_name": "other/repo"}),
        }[kind]
        run[key] = value
    assert gate.main([]) == 1  # nosec B101 -- pytest regression oracle, not runtime authorization.


def test_full_pagination_is_required(evidence):
    gate, rows, entry = evidence
    rows["/releases?per_page=100&page=1"] = [{"tag_name": "v0.0.1"}] * 100
    rows["/releases?per_page=100&page=2"] = [{"tag_name": entry["tag"]}]
    assert gate.main([]) == 1  # nosec B101 -- pytest regression oracle, not runtime authorization.
    rows["/releases?per_page=100&page=2"] = []
    assert gate.main([]) == 0  # nosec B101 -- pytest regression oracle, not runtime authorization.


def test_network_error_in_withdrawal_evidence_is_not_offline_success(evidence, monkeypatch):
    gate, _, _ = evidence
    original = gate._api

    def fetch(endpoint):
        if endpoint.startswith("/git/"):
            raise OSError("network unavailable")
        return original(endpoint)

    monkeypatch.setattr(gate, "_api", fetch)
    assert gate.main([]) == 1  # nosec B101 -- pytest regression oracle, not runtime authorization.


@pytest.mark.parametrize("kind", ["duplicate", "bad_digest", "bad_id", "wrong_repo", "not_draft", "no_reason", "bad_json", "missing"])
def test_invalid_ledger_cannot_remove_debt(evidence, kind):
    gate, _, _ = evidence
    path = withdrawals.LEDGER
    ledger = json.loads(path.read_text())
    entry = ledger["withdrawals"][0]
    if kind == "duplicate":
        ledger["withdrawals"].append(entry.copy())
    elif kind in ("bad_json", "missing"):
        if kind == "missing":
            path.unlink()
        else:
            path.write_text("{broken")
        assert gate.main([]) == 1  # nosec B101 -- pytest regression oracle, not runtime authorization.
        return
    else:
        key, value = {
            "bad_digest": ("tag_object", "../escape"), "bad_id": ("deleted_draft_id", True),
            "wrong_repo": ("repository", "other/repo"), "not_draft": ("was_draft", False),
            "no_reason": ("reason", ""),
        }[kind]
        entry[key] = value
    path.write_text(json.dumps(ledger))
    assert gate.main([]) == 1  # nosec B101 -- pytest regression oracle, not runtime authorization.
