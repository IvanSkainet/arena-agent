"""A failed token rotation must not be an HTTP 200 (#211).

`POST /v1/token/regenerate` ended with `return ctx.cors_json_response(result)`
-- no status argument -- so a rotation that failed to write the token file
came back as::

    HTTP 200
    {"ok": false, "error": "Failed to write /...: [Errno 21] Is a directory"}

Measured on this commit's parent by pointing `token_file` at a directory.

Why that is dangerous rather than untidy. Every HTTP client, proxy and
retry layer treats 2xx as "it worked". A caller that rotates its
credential, sees 200, and writes the response over its stored token
**destroys a working token** -- and is left with nothing valid to retry
with. Recovering needs physical access to the machine. The `ok` field
carried the truth, but a contract that lives only in the body is one that
almost no generated client honours.

The fix is the status, not the envelope: 500 for the write failure, since
`token_regenerate` reports exactly one kind of failure and it is this
end's fault. The body is unchanged.

Two things ride along:

* the audit journal recorded `token_regenerated` for a rotation that did
  not happen, which is the same lie in the other log;
* the OpenAPI entry documented the 200-means-maybe union as if intended
  (#89 declined to legitimise it and said so). It now says 500.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests._live_bridge import auth_header, json_payload, running_client

TOKEN = "token-regenerate-status-211"


def _write_tokens_under(client, tmp_path: Path) -> Path:
    """Point `token_file` at this test's own directory.

    Without it a successful rotation falls through to the default token
    file, and `token_regenerate` writes a live credential into the
    repository checkout -- which then breaks
    `test_check_bridge_diagnostic.py::test_read_token_env_fallback`,
    because `scripts/check_bridge.py` prefers `<repo>/token.txt` over the
    environment. A test that leaves a real secret in the working tree is
    its own defect; it is also the reason this file sets the path even on
    the paths that are expected to succeed.
    """
    from arena.app_keys import APP_CFG

    target = tmp_path / "bridge-token.txt"
    client.app[APP_CFG]["token_file"] = str(target)
    return target


def _break_the_token_file(client, tmp_path: Path) -> None:
    """Point `token_file` at a directory: `write_owner_token` then raises.

    A directory is used rather than a chmod because the test has to fail
    the write on Windows too, where a read-only bit does not stop the
    owner and the CI matrix runs six Windows jobs.
    """
    from arena.app_keys import APP_CFG

    unwritable = tmp_path / "token-file-is-a-directory"
    unwritable.mkdir(exist_ok=True)
    client.app[APP_CFG]["token_file"] = str(unwritable)


def test_a_failed_rotation_is_a_500(tmp_path: Path) -> None:
    """The defect, stated as the status a client actually reads."""
    asyncio.run(_failed_rotation_is_a_500(tmp_path))


async def _failed_rotation_is_a_500(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        _break_the_token_file(client, tmp_path)
        response = await client.post(
            "/v1/token/regenerate", headers=auth_header(TOKEN))
        payload = await json_payload(response)

    assert response.status == 500, payload
    assert payload["ok"] is False, payload
    assert "Failed to write" in payload["error"], payload


def test_a_failed_rotation_never_answers_2xx(tmp_path: Path) -> None:
    """The property, kept separate from the exact code.

    500 is one way to satisfy this. What must never come back is a 2xx for
    a rotation that did not happen, because that is the answer a client
    acts on before it ever looks at `ok`.
    """
    asyncio.run(_failed_rotation_is_not_2xx(tmp_path))


async def _failed_rotation_is_not_2xx(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        _break_the_token_file(client, tmp_path)
        response = await client.post(
            "/v1/token/regenerate", headers=auth_header(TOKEN))
        payload = await json_payload(response)

    assert not (200 <= response.status < 300), (response.status, payload)


def test_the_current_credential_still_works_after_a_failed_rotation(
        tmp_path: Path) -> None:
    """The reason the status matters: nothing was revoked, so nothing is lost.

    A caller that (correctly) keeps its token on a 500 must find that
    token still valid. If a failed rotation had also invalidated the old
    credential, a truthful status would not be enough to recover.
    """
    asyncio.run(_old_token_survives(tmp_path))


async def _old_token_survives(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        _break_the_token_file(client, tmp_path)
        failed = await client.post(
            "/v1/token/regenerate", headers=auth_header(TOKEN))
        assert failed.status == 500

        after = await client.get("/v1/status", headers=auth_header(TOKEN))
        assert after.status == 200, await json_payload(after)


def test_a_successful_rotation_is_still_a_200(tmp_path: Path) -> None:
    """The boundary from the other side: the working path is untouched."""
    asyncio.run(_success_is_200(tmp_path))


async def _success_is_200(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        target = _write_tokens_under(client, tmp_path)
        response = await client.post(
            "/v1/token/regenerate", headers=auth_header(TOKEN))
        payload = await json_payload(response)

    assert response.status == 200, payload
    assert payload["ok"] is True, payload
    assert payload["token"], payload
    assert payload["previous_token_revoked"] is True, payload
    assert payload["written_to"] == [str(target)], payload
    assert target.read_text(encoding="utf-8").strip() == payload["token"]


def test_the_new_token_works_and_the_old_one_stops(tmp_path: Path) -> None:
    """A 200 has to mean the swap really happened, or the status lies again.

    Asserting only on the body would let a handler answer 200 with a token
    it never installed -- the mirror image of this defect.
    """
    asyncio.run(_rotation_takes_effect(tmp_path))


async def _rotation_takes_effect(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        _write_tokens_under(client, tmp_path)
        rotated = await client.post(
            "/v1/token/regenerate", headers=auth_header(TOKEN))
        payload = await json_payload(rotated)
        assert rotated.status == 200, payload
        new_token = payload["token"]

        with_new = await client.get("/v1/status", headers=auth_header(new_token))
        assert with_new.status == 200, await json_payload(with_new)

        with_old = await client.get("/v1/status", headers=auth_header(TOKEN))
        assert with_old.status == 401, await json_payload(with_old)


def test_the_audit_journal_does_not_claim_a_rotation_that_failed(
        tmp_path: Path, monkeypatch) -> None:
    """`token_regenerated` was written whether or not anything was written.

    An operator reading the journal after an incident would see a rotation
    that never happened, which is the same falsehood as the 200 and harder
    to notice.
    """
    events = _recorded_audit_events(monkeypatch)
    asyncio.run(_journal_records_the_failure(tmp_path))

    assert events, "no audit entry was written at all"
    kinds = [entry.get("type") for entry in events]
    assert "token_regenerated" not in kinds, events
    assert "token_regenerate_failed" in kinds, events


async def _journal_records_the_failure(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        _break_the_token_file(client, tmp_path)
        response = await client.post(
            "/v1/token/regenerate", headers=auth_header(TOKEN))
        assert response.status == 500


def test_the_audit_failure_entry_does_not_carry_a_token(
        tmp_path: Path, monkeypatch) -> None:
    """The failure path logs an error string; it must not log a credential.

    `token_regenerate` builds the new token before attempting the write,
    so a careless failure entry could carry a live secret into the journal.
    """
    events = _recorded_audit_events(monkeypatch)
    asyncio.run(_failure_entry_is_clean(tmp_path))

    failures = [e for e in events if e.get("type") == "token_regenerate_failed"]
    assert failures, events
    for entry in failures:
        assert "token" not in entry, entry
        assert set(entry) <= {"type", "error", "client"}, entry


async def _failure_entry_is_clean(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        _break_the_token_file(client, tmp_path)
        assert (await client.post(
            "/v1/token/regenerate", headers=auth_header(TOKEN))).status == 500


def _recorded_audit_events(monkeypatch) -> list[dict]:
    """Capture what the handler hands to `ctx.audit`.

    Reading the journal file would work too, but it depends on where the
    test harness points `audit_path`; the events themselves are what this
    test is about, and intercepting them is order-independent.
    """
    from arena.observability import audit_runtime

    events: list[dict] = []
    original = audit_runtime.write_audit_event

    def recording(event: dict, **kwargs: object) -> dict:
        events.append(dict(event))
        return original(event, **kwargs)

    # Patched at the writer rather than at `unified_bridge.audit`: the
    # handler factories capture the `audit` callable by value while the
    # application is built, so rebinding the module attribute afterwards
    # leaves the running app calling the original and the list empty.
    monkeypatch.setattr(audit_runtime, "write_audit_event", recording)
    return events


@pytest.mark.parametrize("status", ["200", "500"])
def test_the_document_declares_both_outcomes(status: str) -> None:
    """#211 asked for the #89 entry to be corrected once this was fixed.

    The old text described the 200-means-maybe union as the contract. A
    document that legitimises the bug is worse than one that omits it,
    because a client generator will faithfully reproduce it.
    """
    from unittest.mock import MagicMock

    from arena.public.openapi import build_openapi_spec

    responses = build_openapi_spec(MagicMock())[
        "paths"]["/v1/token/regenerate"]["post"]["responses"]
    assert status in responses, sorted(responses)


def test_the_document_no_longer_promises_a_200_on_failure() -> None:
    """The specific sentence #211 objected to must be gone."""
    from unittest.mock import MagicMock

    from arena.public.openapi import build_openapi_spec

    operation = build_openapi_spec(MagicMock())[
        "paths"]["/v1/token/regenerate"]["post"]
    described = operation["description"] + operation["responses"]["200"]["description"]
    assert "ALSO reported with HTTP 200" not in described, described
    assert "500" in operation["description"], operation["description"]

# ---------------------------------------------------------------------------
# The chmod-after-replace window (cubic, P1)
# ---------------------------------------------------------------------------
def _chmod_that_fails_after_the_replace(monkeypatch):
    """Let the first chmod (on the temp file) through, fail the second.

    `write_owner_token` chmods the temporary file, calls `os.replace`, then
    re-applies the mode. Only the second call is after the point of no
    return, so only the second is made to fail.
    """
    from arena import token_storage

    real_chmod = token_storage.os.chmod
    calls = {"n": 0}

    def flaky(path, mode, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise PermissionError("chmod after replace failed")
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(token_storage.os, "chmod", flaky)


def test_a_chmod_failure_after_the_replace_is_not_a_failed_rotation(
        tmp_path: Path, monkeypatch) -> None:
    """The file already holds the new token, so the caller must be told so.

    `os.replace` is atomic and has happened by then. Reporting failure left
    the bridge on the old credential in memory while the next restart would
    read the new one off disk -- every client locked out, with the response
    that caused it saying the rotation had failed (cubic).
    """
    from arena.admin.token import token_regenerate

    target = tmp_path / "token.txt"
    target.write_text("the-old-one", encoding="utf-8")
    _chmod_that_fails_after_the_replace(monkeypatch)

    result = token_regenerate(str(target), default_token_file=target)

    assert result["ok"] is True, result
    assert result["token"] == target.read_text(encoding="utf-8").strip(), result
    assert "warning" in result, result
    assert "permissions" in result["warning"], result


def test_the_handler_keeps_memory_and_disk_in_step_through_that_window(
        tmp_path: Path, monkeypatch) -> None:
    """The end-to-end consequence: the returned token is the one that works.

    This is the assertion that would have caught the lockout. If the
    handler treated the chmod failure as a failed rotation, the new token
    on disk and the old token in `cfg` would disagree, and one of these two
    requests would 401.
    """
    asyncio.run(_memory_and_disk_agree(tmp_path, monkeypatch))


async def _memory_and_disk_agree(tmp_path: Path, monkeypatch) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        target = _write_tokens_under(client, tmp_path)
        _chmod_that_fails_after_the_replace(monkeypatch)

        rotated = await client.post(
            "/v1/token/regenerate", headers=auth_header(TOKEN))
        payload = await json_payload(rotated)
        assert rotated.status == 200, payload

        on_disk = target.read_text(encoding="utf-8").strip()
        assert payload["token"] == on_disk, payload

        works = await client.get("/v1/status", headers=auth_header(on_disk))
        assert works.status == 200, await json_payload(works)


def test_a_write_that_never_happened_is_still_a_failure(tmp_path: Path) -> None:
    """The other side of the split: a real write failure stays a 500.

    Making the chmod window a success must not turn every write error into
    one, which would be the same defect with a wider blast radius.
    """
    asyncio.run(_failed_rotation_is_a_500(tmp_path))


def test_the_mode_warning_names_the_file_and_says_it_took_effect() -> None:
    """An operator reading it must not have to guess which half happened."""
    from arena.token_storage import TokenFileModeWarning

    warned = TokenFileModeWarning(Path("/tmp/token.txt"), PermissionError("nope"))

    assert "/tmp/token.txt" in str(warned)
    assert "DID take effect" in str(warned)


def test_the_200_schema_cannot_describe_a_failure(tmp_path: Path) -> None:
    """A schema that permits `ok: false` at 200 re-opens the defect (cubic).

    A generated client validates against this document; if the success
    schema still accepts the failure shape, the client is entitled to treat
    a failed rotation as a successful one -- which is exactly what #211 is
    about, moved from the code into the contract.
    """
    from unittest.mock import MagicMock

    from arena.public.openapi import build_openapi_spec

    schema = build_openapi_spec(MagicMock())[
        "paths"]["/v1/token/regenerate"]["post"][
        "responses"]["200"]["content"]["application/json"]["schema"]

    assert schema["properties"]["ok"].get("enum") == [True], schema
    assert "token" in schema["required"], schema
    assert schema["properties"]["token"].get("minLength") == 1, schema
