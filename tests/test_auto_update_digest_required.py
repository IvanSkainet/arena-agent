"""An update archive replaces the bridge's own code -- verify it or refuse.

`arena/admin/auto_update.py` downloads a release zip and unpacks it over
the install root. Bug #61: verification was skipped silently whenever the
expected digest was falsy.

    if expected_sha256:
        want = expected_sha256.split(":", 1)[-1].strip().lower()
        if want and want != got:
            return _err(...)

Two nested truthiness checks. Verified by execution against a stubbed
download -- a hand-made archive was accepted under `None`, `""`, `"   "`,
`"sha256:"` and `"sha256:   "`, and refused only when a wrong-but-present
digest was supplied.

`apply_update()` gates this properly: no digest means it demands
`accept_no_verification=True` plus a distinct consent token, so the
Dashboard path was never wide open. But `download_release` is
module-level API, the guard lived one layer above it, and a bare
`download_release(...)` call reads as though it verifies. Skipping
verification is now something a caller states explicitly.

This is the third instance of this exact shape: `if expected and got !=
expected` in the runtime installer (#51), `if not _TOKEN: return True` in
the input helper (#54), and this. An optional check written as a
truthiness test is a check that is off by default.

Sabotage record (mandatory per AGENTS.md):
  1. restoring `if expected_sha256:` around the comparison
     -> test_an_absent_digest_is_refused fails.
  2. dropping the `allow_unverified` requirement
     -> same test fails.
  3. comparing only the first 8 hex characters
     -> test_a_digest_wrong_only_in_its_tail_is_refused fails.
"""
from __future__ import annotations

import hashlib

import pytest

from arena.admin import auto_update as au, auto_update_fetch as auf

ARCHIVE = b"PK\x03\x04" + b"NOT-A-REAL-RELEASE" * 50
DIGEST = hashlib.sha256(ARCHIVE).hexdigest()


@pytest.fixture()
def stubbed_download(monkeypatch, tmp_path):
    """Serve ARCHIVE without a network or the SSRF guard in the way."""
    import arena.security_ssrf as ssrf

    monkeypatch.setattr(ssrf, "_validate_url", lambda url: None)

    class _Response:
        def __init__(self):
            self._data = ARCHIVE

        def read(self, _size=-1):
            data, self._data = self._data, b""
            return data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(auf, "open_public_url", lambda *a, **kw: _Response())
    return str(tmp_path)


def _download(dest, **kwargs):
    return au.download_release(asset_url="https://example.invalid/x.zip",
                               asset_name="x.zip", dest_dir=dest, **kwargs)


# ---------------------------------------------------------------------------
# The fail-open hole.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("digest", [
    None,
    "",
    "   ",
    "sha256:",
    "sha256:   ",
    ":",
])
def test_an_absent_digest_is_refused(stubbed_download, digest):
    """Every spelling of "no digest" must fail closed."""
    result = _download(stubbed_download, expected_sha256=digest)

    assert result["ok"] is False, (
        f"expected_sha256={digest!r} was accepted; the archive replaces "
        "the bridge's own code"
    )
    assert "expected_sha256 is required" in result["error"]


def test_a_wrong_digest_is_refused(stubbed_download):
    result = _download(stubbed_download, expected_sha256="0" * 64)

    assert result["ok"] is False
    assert "mismatch" in result["error"]


def test_a_digest_wrong_only_in_its_tail_is_refused(stubbed_download):
    """The whole hash must be compared, not a prefix.

    A digest of sixty-four zeroes differs in its first byte too, so it
    cannot distinguish a full comparison from a truncated one. This is
    the same lesson the runtime-installer fix (#51) taught.
    """
    tampered = DIGEST[:-1] + ("f" if DIGEST[-1] != "f" else "0")

    result = _download(stubbed_download, expected_sha256=tampered)

    assert result["ok"] is False
    assert "mismatch" in result["error"]


# ---------------------------------------------------------------------------
# The legitimate paths.
# ---------------------------------------------------------------------------

def test_the_correct_digest_is_accepted(stubbed_download):
    result = _download(stubbed_download, expected_sha256=DIGEST)

    assert result["ok"] is True
    assert result["sha256"] == DIGEST
    assert result["verified"] is True


def test_the_github_prefix_form_is_accepted(stubbed_download):
    """GitHub returns `sha256:<hex>`; rejecting that would be a bug."""
    result = _download(stubbed_download, expected_sha256="sha256:" + DIGEST)

    assert result["ok"] is True
    assert result["verified"] is True


def test_digest_comparison_is_case_insensitive(stubbed_download):
    result = _download(stubbed_download, expected_sha256=DIGEST.upper())

    assert result["ok"] is True


def test_unverified_is_possible_but_must_be_asked_for(stubbed_download):
    """The Windows/no-token path still works -- deliberately."""
    result = _download(stubbed_download, expected_sha256=None,
                       allow_unverified=True)

    assert result["ok"] is True
    assert result["verified"] is False, (
        "an unverified download must say so, or the caller cannot audit "
        "which installs were checked"
    )
    assert result["sha256"] == DIGEST


# ---------------------------------------------------------------------------
# apply_update still refuses the unverified path without consent.
# ---------------------------------------------------------------------------

def test_apply_update_still_demands_opt_in_and_consent():
    """The layer above must keep its own guard; this fix is additional."""
    result = au.apply_update(asset_url="https://example.invalid/x.zip",
                             asset_name="x.zip", tag="v9.9.9",
                             expected_sha256=None, consent="whatever")

    assert result["ok"] is False
    assert "expected_sha256 is required" in result["error"]
    assert "accept_no_verification=true" in result["hint"]


def test_apply_update_unverified_consent_differs_from_verified():
    """Reusing a verified consent to trigger an unverified install would
    defeat the opt-in entirely."""
    url = "https://example.invalid/a.zip"
    verified = au.consent_token(tag="v9.9.9", sha256=DIGEST, asset_url=url)
    # v4.165.0 (bug #70): the unverified path now REQUIRES a URL --
    # without a digest it is the only thing the operator is approving.
    unverified = au.consent_token(tag="v9.9.9", sha256="UNVERIFIED",
                                  asset_url=url)

    assert verified != unverified


def test_no_call_site_leaves_verification_to_a_default():
    """Ratchet: `download_release` must never be called without saying
    which mode it is in."""
    import ast
    import pathlib

    source = pathlib.Path(au.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "download_release":
            continue
        keywords = {kw.arg for kw in node.keywords}
        if "allow_unverified" not in keywords:
            offenders.append(node.lineno)

    assert not offenders, (
        "these download_release() calls do not state whether verification "
        f"is required, so they inherit the default: lines {offenders}"
    )
