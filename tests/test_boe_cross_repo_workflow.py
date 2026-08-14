"""Pinned game compatibility must exercise the real Windows transport chain."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "integrations" / "book_of_eternity_compatibility.json"
WORKFLOW = REPO / ".github" / "workflows" / "boe-contract.yml"
CANDIDATE = REPO / ".github" / "workflows" / "release-candidate.yml"
RUNTIMES = REPO / ".github" / "action-runtimes.json"
HARNESS = REPO / "scripts" / "boe_cross_repo_contract.py"
DOC = REPO / "docs" / "integrations" / "BOOK_OF_ETERNITY.md"
yaml = pytest.importorskip("yaml")


def _workflow(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _triggers(workflow: dict) -> dict:
    value = workflow.get("on") or workflow.get(True) or {}
    assert isinstance(value, dict)
    return value


def _runs(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def _harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("boe_cross_repo_contract", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_compatibility_manifest_is_exact_and_commit_pinned() -> None:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(value) == {
        "schemaVersion",
        "name",
        "repository",
        "defaultBranch",
        "commit",
        "protocolRevision",
        "bridgeProject",
        "controlScript",
        "contractTest",
    }
    assert value["schemaVersion"] == 1
    assert value["name"] == "The Book of Eternity: Reborn"
    assert value["repository"] == "StanislavSmetaninSSM/The-Book-of-Eternity-Reborn"
    assert value["defaultBranch"] == "main"
    assert re.fullmatch(r"[0-9a-f]{40}", value["commit"])
    assert value["commit"] == "11ddf9f5a0d1d5d8ccebedf576f8f5621162d168"
    assert value["protocolRevision"] == "boe-gm-terminal-relay-v1"


def test_workflow_runs_on_windows_for_manual_scheduled_change_and_reuse_paths() -> None:
    workflow = _workflow(WORKFLOW)
    triggers = _triggers(workflow)
    assert {"workflow_call", "workflow_dispatch", "schedule", "push", "pull_request"} == set(
        triggers
    )
    assert workflow["permissions"] == {}
    job = workflow["jobs"]["contract"]
    assert job["runs-on"] == "windows-latest"
    assert job["permissions"] == {"contents": "read"}
    assert job["timeout-minutes"] == 30
    for trigger in ("push", "pull_request"):
        paths = set(triggers[trigger]["paths"])
        for required in (
            ".github/workflows/boe-contract.yml",
            ".github/workflows/release-candidate.yml",
            "integrations/book_of_eternity_compatibility.json",
            "scripts/boe_cross_repo_contract.py",
            "arena/game/boe_relay.py",
            "arena/relay/**",
            "bin/arena-relay",
            "unified_bridge.py",
        ):
            assert required in paths


def test_workflow_checks_out_exact_game_pin_and_rejects_stale_upstream() -> None:
    workflow = _workflow(WORKFLOW)
    job = workflow["jobs"]["contract"]
    raw = WORKFLOW.read_text(encoding="utf-8")
    run = _runs(job)
    assert "integrations/book_of_eternity_compatibility.json" in run
    assert "game_sha=$($manifest.commit)" in run
    assert "git ls-remote" in run
    assert "game pin is stale" in run
    assert "git -C game rev-parse HEAD" in run
    assert "repository: ${{ steps.pin.outputs.game_repository }}" in raw
    assert "ref: ${{ steps.pin.outputs.game_sha }}" in raw
    assert "ARENA_SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in raw
    assert "ref: ${{ env.ARENA_SOURCE_SHA }}" in raw
    assert "ARENA_COMMIT: ${{ env.ARENA_SOURCE_SHA }}" in raw
    assert "persist-credentials: false" in raw


def test_workflow_builds_release_and_game_then_runs_real_contract() -> None:
    job = _workflow(WORKFLOW)["jobs"]["contract"]
    run = _runs(job)
    for required in (
        "scripts/make_release_zip.py",
        "scripts/verify_release_zip.py",
        "BookOfEternityGMBridge.csproj",
        "Helper_CompleteBoeTurnWritesCorrelatedTerminalSignal",
        "scripts/boe_cross_repo_contract.py",
        "arena-artifact/arena-bridge",
        "contract-evidence.json",
        "contract evidence source SHA mismatch",
        "expected three dispatches",
        "relay mailbox did not drain",
        "GM bridge process identity evidence is missing",
        "GM bridge process tree survived shutdown",
        "Arena Bridge server process survived shutdown",
        "contract runtime cleanup failed",
    ):
        assert required in run
    assert "runs-on: windows-latest" in WORKFLOW.read_text(encoding="utf-8")
    step_names = [str(step.get("name", "")) for step in job["steps"]]
    assert step_names.index("Build and verify the Arena release artifact") < step_names.index(
        "Checkout pinned game source"
    )
    assert any(
        str(step.get("uses", "")).startswith("actions/upload-artifact@")
        and step.get("if") == "always()"
        for step in job["steps"]
    )


def test_every_cross_repo_action_is_commit_pinned_and_runtime_recorded() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    refs = re.findall(r"uses:\s*([^\s]+)", raw)
    runtime_map = json.loads(RUNTIMES.read_text(encoding="utf-8"))
    assert refs
    for ref in refs:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref), ref
        assert ref in runtime_map, ref
    setup_dotnet = "actions/setup-dotnet@a98b56852c35b8e3190ac28c8c2271da59106c68"
    assert runtime_map[setup_dotnet] == "node24"


def test_release_candidate_cannot_attest_before_cross_repo_contract() -> None:
    jobs = _workflow(CANDIDATE)["jobs"]
    contract = jobs["boe-contract"]
    assert contract["uses"] == "./.github/workflows/boe-contract.yml"
    assert contract["permissions"] == {"contents": "read"}
    assert set(jobs["attest"]["needs"]) == {
        "boe-contract",
        "build-primary",
        "build-rebuild",
    }


def test_harness_defines_two_turns_then_correlated_repair_without_game_rules() -> None:
    module = _harness()
    dispatches = module._dispatches()
    assert module.PROTOCOL_REVISION == "boe-gm-terminal-relay-v1"
    assert [item.kind for item in dispatches] == ["turn", "turn", "repair"]
    assert [item.turn_number for item in dispatches] == [101, 102, 102]
    assert all("\n" in item.prompt for item in dispatches)
    first_lines = [item.prompt.splitlines()[0] for item in dispatches]
    assert len(set(first_lines)) == len(dispatches)
    assert all(len(line) >= 24 for line in first_lines)
    assert len(dispatches[0].prompt) > 2_000
    assert dispatches[1].request_id == dispatches[2].request_id

    source = HARNESS.read_text(encoding="utf-8")
    assert "arena-relay" in source
    assert 'f"& {_powershell_literal(sys.executable)} "' in source
    assert module._powershell_literal("C:\\O'Brien\\relay.py") == "'C:\\O''Brien\\relay.py'"
    assert "dispatchPrompt" in source
    assert "/v1/relay/poll?wait=25" in source
    assert "/v1/relay/reply" in source
    assert "complete_turn" in source
    assert "repair_ready" in source
    assert "remainingProcessIds" in source
    assert "shutil.rmtree(temp)" in source
    assert "temporaryDirectoryRemoved" in source
    assert "dice" not in source.lower()


def test_documentation_keeps_transport_and_game_engine_boundaries_separate() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "The Book of Eternity: Reborn" in text
    assert "transport, not a second game engine" in text
    assert "11ddf9f5a0d1d5d8ccebedf576f8f5621162d168" in text
    assert "arena-relay terminal" in text
    flattened = " ".join(text.split())
    assert "does not implement game rules" in flattened
    assert "release-candidate workflow calls this reusable Windows contract" in flattened
