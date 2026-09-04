"""Release assets must be verifiable, and the workflow that signs them must stay honest.

Until now a download could not be checked at all. The release page offered
two zips and nothing to check them against: no digest in the body, no
signature file, nothing. Measured on v4.160.0 -- ``body mentions sha256:
False``. Anyone with write access, or anyone able to intercept the download,
could swap the archive and no user could tell. This project ships a tool that
executes commands on the operator's machine, so "you cannot verify what you
downloaded" is a real gap.

``.github/workflows/sign-release.yml`` closes it with Sigstore keyless
signing. Keyless matters here: there is no private key to leak, rotate, or
commit by accident. GitHub mints a short-lived OIDC token, Sigstore binds the
signature to *this workflow in this repository*, and the certificate lands in
a public transparency log. Verification proves the artifact came from this
workflow -- a stronger claim than "somebody holding a key signed it".

These tests guard the properties that make that claim true. A signing
pipeline is easy to weaken by accident: drop ``id-token: write`` and it stops
working, drop the verify step and nobody notices it stopped, loosen the
identity regex and any workflow in any repo can satisfy it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

WORKFLOW = REPO / ".github" / "workflows" / "sign-release.yml"

yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def wf() -> dict:
    assert WORKFLOW.exists(), "the release-signing workflow is missing"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sign_job(wf) -> dict:
    jobs = wf.get("jobs") or {}
    assert "sign" in jobs, f"expected a 'sign' job, found {list(jobs)}"
    return jobs["sign"]


def test_it_runs_when_a_release_is_published(wf):
    # PyYAML parses a bare `on:` key as the boolean True.
    triggers = wf.get("on") or wf.get(True) or {}
    assert "release" in triggers, (
        "signing must be triggered by publishing a release; a workflow that "
        "only runs manually will be forgotten on the release that matters")
    assert "published" in (triggers["release"].get("types") or [])


def test_the_job_can_actually_sign(sign_job):
    """Keyless signing needs an OIDC token; without it every run fails."""
    perms = sign_job.get("permissions") or {}
    assert perms.get("id-token") == "write", (
        "id-token: write is what lets GitHub mint the OIDC token Sigstore "
        f"needs; got {perms}")
    assert perms.get("contents") == "write", "signatures must be uploadable"


def test_top_level_permissions_are_empty(wf):
    """Same rule as every other workflow here: grant nothing by default."""
    assert wf.get("permissions") == {}, (
        "top-level permissions must be {}; the job declares its own scope")


def test_every_action_is_pinned_to_a_commit_sha(raw):
    """A moving tag is a supply-chain hole in the thing that proves supply chain."""
    uses = re.findall(r"uses:\s*([^\s]+)", raw)
    assert uses, "no actions found; did the workflow change shape?"
    for ref in uses:
        assert "@" in ref, f"unpinned action: {ref}"
        _, sha = ref.rsplit("@", 1)
        assert re.fullmatch(r"[0-9a-f]{40}", sha), (
            f"{ref} is pinned to a tag, not a commit SHA. Tags move; a signing "
            "workflow pinned to a movable ref undermines its own guarantee.")


def test_it_verifies_what_it_signed(raw):
    """A signing step nobody has watched succeed is a signing step that may not."""
    assert "cosign verify-blob" in raw, (
        "the workflow signs but never verifies; add a verify step so a broken "
        "bundle is caught before users meet it")


def test_verification_is_bound_to_this_workflow_and_repo(raw):
    """A loose identity check would accept a signature from anywhere."""
    assert "--certificate-identity-regexp" in raw
    assert "sign-release" in raw, "identity must name this workflow"
    assert "GITHUB_REPOSITORY" in raw, "identity must name this repository"
    # Match the whole flag-and-value, not a bare URL substring: CodeQL flags
    # `"https://..." in text` as incomplete URL sanitization, and it is right
    # about the shape even though this only greps a workflow file we own.
    assert re.search(
        r'--certificate-oidc-issuer\s+"?https://token\.actions\.githubusercontent\.com"?(?!\w)',
        raw), ("the OIDC issuer must be pinned to GitHub's, or another issuer "
               "could vouch for a signature")


def test_it_publishes_digests_too(raw):
    """Not everyone will install cosign; a checksum file is the fallback."""
    assert "sha256sum" in raw
    assert "SHA256SUMS" in raw


def test_it_fails_closed_unless_the_exact_release_asset_set_exists(raw):
    """Missing ZIP/APK assets or extra ZIPs must never reach signing."""
    assert "release must contain exactly" in raw
    assert '[ "$zip_count" -ne 2 ]' in raw
    assert 'versioned="arena-agent-${TAG}.zip"' in raw
    assert 'alias="arena-agent.zip"' in raw
    assert 'apk="arena-bridge.apk"' in raw
    assert '[ ! -f "$apk" ]' in raw
    assert raw.count("set -euo pipefail") >= 4, (
        "each run block needs strict mode, or a failed command mid-script "
        "leaves the job green")


def test_release_docs_tell_the_user_how_to_verify():
    """A signature nobody knows how to check protects nobody."""
    release_md = (REPO / "RELEASE.md").read_text(encoding="utf-8")
    assert "cosign verify-blob" in release_md, (
        "RELEASE.md must show the verification command; an unverifiable "
        "signature is decoration")


# ---------------------------------------------------------------------
# Signing must happen before publication (#252)
#
# v4.170.0 shipped with no .sig/.pem at all. The signatures were produced
# and verified, then the upload failed:
#     HTTP 422: Cannot upload assets to an immutable release
# A published release freezes its asset list, and
# `PATCH {"immutable": false}` returns 200 without changing anything, so
# it cannot be repaired after the fact.
#
# Measured against the v4.169.38 draft: asset download HTTP 200, upload
# HTTP 201, delete HTTP 204. Drafts are writable, published releases are
# not -- so the draft is the only window in which signing can work.
# ---------------------------------------------------------------------


def test_the_workflow_can_be_run_on_demand_for_a_tag(wf):
    """Signing a draft requires a manual trigger.

    `release: published` fires only after the freeze, so it can never
    attach anything to an immutable release. workflow_dispatch with a tag
    is what makes draft signing possible.
    """
    on = wf.get("on") or wf.get(True)
    assert "workflow_dispatch" in on, "no manual trigger: a draft cannot be signed"
    inputs = on["workflow_dispatch"]["inputs"]
    assert "tag" in inputs, "the manual trigger must accept the tag to sign"
    assert inputs["tag"]["required"] is True


def test_it_refuses_to_sign_an_immutable_release_with_a_clear_message(raw):
    """A bare HTTP 422 sent me looking in the wrong place for an hour.

    The failure must name the cause and the fix, not just the status
    code -- otherwise the next person reads "upload failed" and retries,
    which cannot work.
    """
    # Assert on the guard, not on prose. Sabotage caught this: deleting
    # the actual API call left the word "immutable" in a comment and the
    # test stayed green.
    assert 'immutable=$(gh api' in raw, (
        "nothing queries the release's immutable flag before uploading"
    )
    assert 'if [ "$immutable" = "true" ]' in raw, (
        "the immutable flag is read but never acted on"
    )
    assert "draft" in raw.lower(), "the error must point at draft signing"


def test_the_public_download_check_is_skipped_for_a_draft(raw):
    """A draft has no public URL, so that check must not fail the run.

    Skipped deliberately rather than deleted: it still runs on the
    published release via the release:published trigger.
    """
    assert "steps.draft.outputs.draft != 'true'" in raw, (
        "the anonymous download step must be conditional; a draft has no "
        "public download URL and the step would fail every draft signing"
    )


def test_release_docs_put_signing_before_publication():
    """RELEASE.md must lead to the working order, not the broken one.

    The old step 8 ended with `--draft=false` immediately after creating
    the draft, so signing could only ever run post-freeze. The document
    is what an agent follows; leaving it stale reproduces the bug.
    """
    doc = (REPO / "RELEASE.md").read_text(encoding="utf-8")
    sign_at = doc.find("gh workflow run sign-release.yml")
    publish_at = doc.find("gh release edit vX.Y.Z --draft=false")
    assert sign_at != -1, "RELEASE.md never triggers signing"
    assert publish_at != -1, "RELEASE.md never publishes the draft"
    assert sign_at < publish_at, (
        "RELEASE.md still publishes before signing; a published release "
        "is immutable and can never receive its signatures (#252)"
    )
    assert "immutable" in doc, "the reason for the order is not recorded"
