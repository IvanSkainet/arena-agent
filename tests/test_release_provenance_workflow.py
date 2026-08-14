"""Release signing must accept only reproducible, source-attested candidate bytes."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO / ".github" / "workflows" / "release-candidate.yml"
SIGN = REPO / ".github" / "workflows" / "sign-release.yml"
RUNTIMES = REPO / ".github" / "action-runtimes.json"
yaml = pytest.importorskip("yaml")


def _workflow(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _runs(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def test_candidate_is_manual_exact_sha_build_not_a_release_publisher() -> None:
    workflow = _workflow(CANDIDATE)
    triggers = workflow.get("on") or workflow.get(True) or {}
    assert set(triggers) == {"workflow_dispatch"}
    assert workflow["permissions"] == {}
    raw = CANDIDATE.read_text(encoding="utf-8")
    assert "gh release create" not in raw
    assert "gh release upload" not in raw
    assert "release:" not in raw


def test_two_independent_builds_must_match_before_attestation() -> None:
    jobs = _workflow(CANDIDATE)["jobs"]
    assert {"build-primary", "build-rebuild", "attest"} <= set(jobs)
    assert set(jobs["attest"]["needs"]) == {
        "boe-contract",
        "build-primary",
        "build-rebuild",
    }
    for name in ("build-primary", "build-rebuild"):
        run = _runs(jobs[name])
        assert "scripts/make_release_zip.py" in run
        assert jobs[name]["permissions"] == {"contents": "read"}
    attest_run = _runs(jobs["attest"])
    assert "cmp \"$a\" \"$b\"" in attest_run
    assert "scripts/verify_release_zip.py" in attest_run
    assert "sha256sum" in attest_run


def test_attestation_job_has_narrow_oidc_permissions_and_two_predicates() -> None:
    job = _workflow(CANDIDATE)["jobs"]["attest"]
    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    attest_steps = [
        step for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/attest@")
    ]
    assert len(attest_steps) == 2
    assert all("subject-checksums" in step["with"] for step in attest_steps)
    assert sum("sbom-path" in step["with"] for step in attest_steps) == 1
    raw = CANDIDATE.read_text(encoding="utf-8")
    assert "format: spdx-json" in raw
    assert "upload-release-assets: false" in raw


def test_every_candidate_action_is_commit_pinned_and_runtime_recorded() -> None:
    raw = CANDIDATE.read_text(encoding="utf-8")
    uses = re.findall(r"uses:\s*([^\s]+)", raw)
    assert uses
    runtime_map = json.loads(RUNTIMES.read_text(encoding="utf-8"))
    for ref in uses:
        if ref.startswith("./"):
            assert ref == "./.github/workflows/boe-contract.yml"
            continue
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref), ref
        assert ref in runtime_map, f"missing action runtime record: {ref}"
    attest_ref = "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
    assert runtime_map[attest_ref] == "node24"


def test_signing_refuses_unattested_or_wrong_workflow_bytes() -> None:
    raw = SIGN.read_text(encoding="utf-8")
    verify_at = raw.index("gh attestation verify")
    cosign_at = raw.index("cosign sign-blob")
    assert verify_at < cosign_at
    assert "--signer-workflow" in raw
    assert "release-candidate.yml" in raw
    assert "--deny-self-hosted-runners" in raw
    assert "https://spdx.dev/Document/v2.3" in raw


def test_signing_binds_attestations_to_exact_tag_commit() -> None:
    raw = SIGN.read_text(encoding="utf-8")
    assert '"repos/${GITHUB_REPOSITORY}/commits/${TAG}"' in raw
    assert "source_digest=$source_digest" in raw
    assert raw.count('--source-digest "$SOURCE_DIGEST"') == 2
    assert "SOURCE_DIGEST: ${{ steps.tag.outputs.source_digest }}" in raw


def test_signing_accepts_only_the_exact_identical_zip_pair() -> None:
    raw = SIGN.read_text(encoding="utf-8")
    assert "[ \"$count\" -ne 2 ]" in raw
    assert 'versioned="arena-agent-${TAG}.zip"' in raw
    assert 'alias="arena-agent.zip"' in raw
    assert 'cmp "$versioned" "$alias"' in raw
    assert 'for f in "arena-agent-${TAG}.zip" arena-agent.zip; do' in raw
    assert 'sha256sum "arena-agent-${TAG}.zip" arena-agent.zip' in raw
    assert 'attested-release-candidate-${SOURCE_DIGEST}' in raw
    assert '(cd "$accepted" && sha256sum -c "$(basename "$manifest")")' in raw
    assert '(cd dist && sha256sum -c "$manifest")' in raw
    assert 'cmp "$accepted/arena-agent-${TAG}.zip"' in raw
    assert "sha256sum --check \"SHA256SUMS-${TAG}.txt\"" in raw
    assert "--ignore-missing" not in raw


def test_candidate_final_artifact_contains_evidence_and_bundles() -> None:
    raw = CANDIDATE.read_text(encoding="utf-8")
    for required in (
        "release-verification.json",
        "release-candidate.json",
        "provenance-bundle.jsonl",
        "sbom-attestation-bundle.jsonl",
        "arena-agent.spdx.json",
        "SHA256SUMS-candidate-",
        "attested-release-candidate-${{ github.sha }}",
    ):
        assert required in raw
