"""T46: Android releases are exact-SHA candidate assets, not CI leftovers."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO / ".github" / "workflows" / "release-candidate.yml"
SIGN = REPO / ".github" / "workflows" / "sign-release.yml"
BUILD = REPO / "scripts" / "build_android_apk.sh"
CERT = REPO / "android_app" / "release-signing-cert.sha256"
yaml = pytest.importorskip("yaml")


def _workflow(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _runs(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def test_candidate_has_one_exact_sha_release_apk_job() -> None:
    jobs = _workflow(CANDIDATE)["jobs"]
    apk = jobs["build-apk"]
    assert apk["permissions"] == {"contents": "read"}
    checkout = next(
        step for step in apk["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["persist-credentials"] is False
    assert "build-apk" in set(jobs["attest"]["needs"])


def test_release_identity_secrets_are_required_and_never_defaulted_in_workflow() -> None:
    apk = _workflow(CANDIDATE)["jobs"]["build-apk"]
    raw = CANDIDATE.read_text(encoding="utf-8")
    for name in (
        "ANDROID_RELEASE_KEYSTORE_B64",
        "ANDROID_RELEASE_KEY_ALIAS",
        "ANDROID_RELEASE_STORE_PASSWORD",
        "ANDROID_RELEASE_KEY_PASSWORD",
    ):
        assert f"secrets.{name}" in raw
    restore = next(step for step in apk["steps"] if step.get("name") == "Restore persistent Android release identity")
    run = str(restore["run"])
    assert "Android release signing secret missing" in run
    assert 'base64 --decode > "$RUNNER_TEMP/arena-release.jks"' in run
    assert 'chmod 600 "$RUNNER_TEMP/arena-release.jks"' in run


def test_apk_builder_separates_disposable_ci_key_from_release_key() -> None:
    source = BUILD.read_text(encoding="utf-8")
    assert 'KS="${ARENA_ANDROID_KEYSTORE:-$BUILD/arena.jks}"' in source
    assert 'if [ -n "${ARENA_ANDROID_KEYSTORE:-}" ]; then' in source
    assert "configured release keystore is missing" in source
    assert "--ks-pass env:ARENA_ANDROID_STORE_PASSWORD" in source
    assert "--key-pass env:ARENA_ANDROID_KEY_PASSWORD" in source
    assert '--ks-key-alias "$KEY_ALIAS"' in source


def test_candidate_verifies_apk_identity_version_signature_and_cert() -> None:
    run = _runs(_workflow(CANDIDATE)["jobs"]["build-apk"])
    for marker in (
        "scripts/android_lint.py",
        "scripts/build_android_apk.sh",
        "package: name='ai.arena.bridge'",
        "versionName='$version'",
        "apksigner\" verify --verbose --print-certs",
        "Signer #1 certificate SHA-256 digest:",
        "release-signing-cert.sha256",
        'test "$actual_cert" = "$expected_cert"',
        "apk-sha256.txt",
    ):
        assert marker in run
    fingerprint = CERT.read_text(encoding="utf-8").strip()
    assert len(fingerprint) == 64
    assert set(fingerprint) <= set("0123456789abcdef")
    raw = CANDIDATE.read_text(encoding="utf-8")
    assert "name: release-apk" in raw
    assert "android_app/build/arena-bridge.apk" in raw


def test_candidate_provenance_and_sboms_cover_apk_separately() -> None:
    raw = CANDIDATE.read_text(encoding="utf-8")
    assert "candidate-apk/arena-bridge.apk" in raw
    assert "dist/arena-bridge.apk" in raw
    assert "SHA256SUMS-candidate-v${VERSION}.txt" in raw
    assert "SHA256SUMS-apk-sbom-v${VERSION}.txt" in raw
    assert "output-file: dist/arena-bridge.spdx.json" in raw
    assert "sbom-path: dist/arena-bridge.spdx.json" in raw
    assert "apk-sbom-attestation-bundle.jsonl" in raw
    assert '"schemaVersion": 2' in raw
    assert '"androidCertificateSha256"' in raw
    assert '"arena-bridge.apk"' in raw


def test_release_signing_fails_closed_without_candidate_apk_and_signs_it() -> None:
    raw = SIGN.read_text(encoding="utf-8")
    assert "--pattern 'arena-bridge.apk'" in raw
    assert '[ ! -f "$apk" ]' in raw
    assert 'test "$(wc -l < "$manifest")" -eq 3' in raw
    assert 'cmp "$accepted/arena-bridge.apk" dist/arena-bridge.apk' in raw
    assert 'arena-agent.zip arena-bridge.apk "SHA256SUMS-${TAG}.txt"' in raw
    assert "releases/download/${TAG}/arena-bridge.apk" in raw
