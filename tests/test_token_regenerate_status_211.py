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
import os
import time
from pathlib import Path

import pytest

from arena import token_storage
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
def _mode_change_that_fails_after_the_replace(monkeypatch):
    """Let the pre-replace chmod through, fail the post-replace one.

    `write_owner_token` chmods the temporary file by path, calls
    `os.replace`, then re-applies the mode through the descriptor it kept
    open (`os.fchmod`, so a swapped path cannot redirect it). Only that
    second call is past the point of no return, so only it is made to
    fail.
    """
    def denied(_fd, _mode, *args, **kwargs):
        raise PermissionError("chmod after replace failed")

    monkeypatch.setattr(token_storage.os, "fchmod", denied)


def _after_the_replace(monkeypatch, tamper):
    """Run `tamper()` at the post-replace mode change, then succeed.

    Used to model another process reaching the path in the window the
    identity check guards, with the mode change itself working fine.
    """
    real_fchmod = token_storage.os.fchmod

    def meddles(fd, mode, *args, **kwargs):
        result = real_fchmod(fd, mode, *args, **kwargs)
        tamper()
        return result

    monkeypatch.setattr(token_storage.os, "fchmod", meddles)


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
    _mode_change_that_fails_after_the_replace(monkeypatch)

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
        _mode_change_that_fails_after_the_replace(monkeypatch)

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


def test_the_mode_warning_names_the_file_and_says_it_took_effect(
        tmp_path: Path) -> None:
    """An operator reading it must not have to guess which half happened.

    The path is rendered with `str(Path)`, which is `\\tmp\\token.txt` on
    Windows and `/tmp/token.txt` elsewhere, so the assertion compares
    against the same rendering rather than a hardcoded POSIX spelling --
    the first revision of this test failed on all five Windows jobs for
    exactly that reason.
    """
    from arena.token_storage import TokenFileModeWarning

    target = tmp_path / "token.txt"
    warned = TokenFileModeWarning(target, PermissionError("nope"))

    assert str(target) in str(warned)
    assert "DID take effect" in str(warned)
    assert warned.target == target


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


# ---------------------------------------------------------------------------
# The replace/chmod window: only downgrade when the file is still ours
# (cubic, P2). A warning means "the new token is on disk"; if the path was
# removed or swapped in that window, that claim is false and the caller must
# hear about it as a failure.
# ---------------------------------------------------------------------------

def test_a_file_deleted_between_replace_and_chmod_is_a_hard_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A vanished token file must not be reported as a rotation that took."""
    target = tmp_path / "token.txt"
    target.write_text("OLD-TOKEN", encoding="utf-8")
    def deletes_then_fails(_fd, _mode, *args, **kwargs):
        os.unlink(target)
        raise FileNotFoundError(2, "No such file or directory", str(target))

    monkeypatch.setattr(token_storage.os, "fchmod", deletes_then_fails)

    with pytest.raises(token_storage.TokenFileVanishedError):
        token_storage.write_owner_token(target, "NEW-TOKEN")
    assert not target.exists()


@pytest.mark.skipif(os.name != "posix", reason="inode identity is POSIX-only")
def test_a_file_swapped_between_replace_and_chmod_is_a_hard_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A different file at the same path is not the rotation we performed."""
    target = tmp_path / "token.txt"
    target.write_text("OLD-TOKEN", encoding="utf-8")
    intruder = tmp_path / "intruder.txt"
    intruder.write_text("SOMEONE-ELSES-TOKEN", encoding="utf-8")
    def swaps_then_fails(_fd, _mode, *args, **kwargs):
        os.replace(intruder, target)
        raise PermissionError("mode change denied")

    monkeypatch.setattr(token_storage.os, "fchmod", swaps_then_fails)

    with pytest.raises(token_storage.TokenFileVanishedError):
        token_storage.write_owner_token(target, "NEW-TOKEN")
    assert target.read_text(encoding="utf-8") == "SOMEONE-ELSES-TOKEN"


def test_the_untouched_path_still_warns_rather_than_failing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The identity check must not undo the fix it guards."""
    target = tmp_path / "token.txt"
    seen: list[int] = []

    def fails_after_replace(fd, _mode, *args, **kwargs):
        seen.append(fd)
        raise PermissionError("mode change denied")

    monkeypatch.setattr(token_storage.os, "fchmod", fails_after_replace)

    with pytest.raises(token_storage.TokenFileModeWarning):
        token_storage.write_owner_token(target, "NEW-TOKEN")
    assert seen, "the post-replace chmod never ran"
    assert target.read_text(encoding="utf-8") == "NEW-TOKEN"


# ---------------------------------------------------------------------------
# First-start bootstrap (cubic, P2)
# ---------------------------------------------------------------------------

def test_first_start_survives_a_chmod_failure_after_the_replace(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bridge must not refuse to start over a permission bit.

    `resolve_token` generates the very first token. Before this fix the
    warning escaped as an exception, so a filesystem that would not take
    the re-chmod killed the process even though the credential had been
    written and was usable.
    """
    from arena.bootstrap_token import resolve_token

    target = tmp_path / "token.txt"
    _mode_change_that_fails_after_the_replace(monkeypatch)
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    monkeypatch.delenv("ARENA_LOCAL_BRIDGE_TOKEN", raising=False)
    logged: list[str] = []

    token, path = resolve_token(
        None,
        default_token_file=target,
        token_generator=lambda: "a-generated-token-value",
        log_info=lambda fmt, *a: logged.append(fmt % a))

    assert token == "a-generated-token-value"
    assert path == target
    assert target.read_text(encoding="utf-8").strip() == token
    assert any("mode could not be set" in line for line in logged), logged


def test_first_start_still_dies_when_nothing_was_written(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tolerating the warning must not tolerate a real write failure."""
    from arena.bootstrap_token import resolve_token

    target = tmp_path / "token.txt"

    def denied(*_args, **_kwargs):
        raise OSError("chmod denied")

    monkeypatch.setattr(token_storage.os, "chmod", denied)
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    monkeypatch.delenv("ARENA_LOCAL_BRIDGE_TOKEN", raising=False)

    with pytest.raises(OSError, match="chmod denied"):
        resolve_token(
            None,
            default_token_file=target,
            token_generator=lambda: "a-generated-token-value")
    assert not target.exists()


def test_the_write_docstring_does_not_promise_that_everything_propagates(
        ) -> None:
    """The stale guarantee is what a future reader would revert the fix on.

    Asserting on prose is normally a smell, but this exact sentence is the
    one cubic flagged: it told readers that any failure propagates, which
    is no longer true and directly contradicts the warning path.
    """
    doc = token_storage.write_owner_token.__doc__ or ""

    assert "Any failure propagates" not in doc
    assert "TokenFileModeWarning" in doc


@pytest.mark.skipif(
    os.name != "posix",
    reason=(
        "`_still_ours` compares st_ino, which Windows does not expose as a "
        "stable identity, so a same-path swap is indistinguishable from our "
        "own file there and only the delete case is detectable. Verified: "
        "this test was the single failure across the five windows-latest "
        "jobs while the delete and end-to-end cases passed."))
def test_a_swap_is_caught_even_when_the_chmod_itself_succeeds(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The identity check must not hide in the chmod failure path.

    cubic, P1 on the previous commit: the guard only ran when the chmod
    raised, so a process that replaced the path while the chmod happily
    succeeded produced a reported-successful rotation for a token that is
    not on disk -- the exact failure the guard was added to prevent.
    """
    target = tmp_path / "token.txt"
    target.write_text("OLD-TOKEN", encoding="utf-8")
    intruder = tmp_path / "intruder.txt"
    intruder.write_text("SOMEONE-ELSES-TOKEN", encoding="utf-8")
    _after_the_replace(monkeypatch, lambda: os.replace(intruder, target))

    with pytest.raises(token_storage.TokenFileVanishedError):
        token_storage.write_owner_token(target, "NEW-TOKEN")
    assert target.read_text(encoding="utf-8") == "SOMEONE-ELSES-TOKEN"


def test_a_vanished_file_is_not_a_mode_warning(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The two post-replace outcomes must stay distinguishable by type.

    A caller decides whether to keep the new token in memory on exactly
    this distinction, so `TokenFileVanishedError` must not be catchable as
    the warning that means "rotated, check the permissions".
    """
    target = tmp_path / "token.txt"
    _after_the_replace(monkeypatch, lambda: os.unlink(target))

    assert not issubclass(
        token_storage.TokenFileVanishedError, token_storage.TokenFileModeWarning)
    with pytest.raises(token_storage.TokenFileVanishedError):
        token_storage.write_owner_token(target, "NEW-TOKEN")


def test_the_bridge_does_not_start_on_a_token_that_vanished(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """First start tolerates the mode warning, not a disappeared file."""
    from arena.bootstrap_token import resolve_token

    target = tmp_path / "token.txt"
    _after_the_replace(monkeypatch, lambda: os.unlink(target))
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    monkeypatch.delenv("ARENA_LOCAL_BRIDGE_TOKEN", raising=False)

    with pytest.raises(token_storage.TokenFileVanishedError):
        resolve_token(
            None,
            default_token_file=target,
            token_generator=lambda: "a-generated-token-value")


def test_the_api_reports_a_vanished_token_as_a_failed_rotation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end: a token that did not survive is a 500, not a warning.

    The warning path answers 200 with a `warning` field on purpose. This
    asserts the other post-replace outcome takes the failure path all the
    way out to the status a client reads, so the two can never be conflated
    at the HTTP boundary.
    """
    seen: list[Path] = []
    victim = tmp_path / "token.txt"

    def unlink_the_token():
        if victim.exists():
            seen.append(victim)
            os.unlink(victim)

    _after_the_replace(monkeypatch, unlink_the_token)
    asyncio.run(_vanished_token_is_a_500(tmp_path, seen))


async def _vanished_token_is_a_500(tmp_path: Path, seen: list[Path]) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        from arena.app_keys import APP_CFG

        client.app[APP_CFG]["token_file"] = str(tmp_path / "token.txt")
        response = await client.post(
            "/v1/token/regenerate", headers=auth_header(TOKEN))
        payload = await json_payload(response)

    assert seen, "the token file was never written"
    assert response.status == 500, payload
    assert payload["ok"] is False, payload
    assert "warning" not in payload, payload


@pytest.mark.skipif(
    os.name != "posix",
    reason=(
        "the descriptor is only held across the rename on POSIX; Windows "
        "refuses to rename an open file (WinError 32), so it settles by "
        "path there"))
def test_a_swap_before_the_first_stat_does_not_chmod_a_foreign_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The reason the mode is re-applied through the descriptor.

    CodeRabbit, #211: resolving the path a second time reopens the window
    the identity check exists to close. If the swap lands before that
    lookup, a path-based implementation chmods the intruder's file to 0600
    and then records its inode as the one it installed -- so the check
    compares the foreign file against itself and passes.

    Here the swap happens inside `os.replace`, i.e. before anything looks
    the path up again. Two things must hold: the rotation is refused, and
    the intruder's file is left exactly as it was.
    """
    target = tmp_path / "token.txt"
    target.write_text("OLD-TOKEN", encoding="utf-8")
    intruder = tmp_path / "intruder.txt"
    intruder.write_text("SOMEONE-ELSES-TOKEN", encoding="utf-8")
    os.chmod(intruder, 0o644)
    real_replace = token_storage.os.replace

    def swaps_right_after(src, dst, *args, **kwargs):
        result = real_replace(src, dst, *args, **kwargs)
        if Path(dst) == target:
            real_replace(str(intruder), str(target))
        return result

    monkeypatch.setattr(token_storage.os, "replace", swaps_right_after)

    with pytest.raises(token_storage.TokenFileVanishedError):
        token_storage.write_owner_token(target, "NEW-TOKEN")

    assert target.read_text(encoding="utf-8") == "SOMEONE-ELSES-TOKEN"
    assert target.stat().st_mode & 0o777 == 0o644, (
        "the foreign file's mode was changed, so the chmod followed the path "
        "rather than the descriptor")


# ---------------------------------------------------------------------------
# Concurrent rotations (CodeRabbit, Major)
# ---------------------------------------------------------------------------

def test_overlapping_rotations_leave_memory_and_disk_agreeing(
        tmp_path: Path) -> None:
    """The same divergence as #211, reached from the other direction.

    The write runs in an eight-worker executor, so two authenticated
    requests overlap freely. Unserialised, the executor can finish A last
    while B installs itself into `cfg["token"]`, leaving the live
    credential and the token file holding different values -- measured on
    the unlocked code: two runs in six diverged. Nothing is wrong until the
    bridge restarts and reads the file, at which point every client is
    locked out, which is exactly the outcome this PR exists to prevent.
    """
    asyncio.run(_overlapping_rotations_agree(tmp_path))


async def _overlapping_rotations_agree(tmp_path: Path) -> None:
    from arena.app_keys import APP_CFG

    async with running_client(tmp_path, TOKEN) as client:
        client.app[APP_CFG]["token_file"] = str(tmp_path / "token.txt")
        responses = await asyncio.gather(*[
            client.post("/v1/token/regenerate", headers=auth_header(TOKEN))
            for _ in range(8)])
        handed_out = []
        for response in responses:
            payload = await json_payload(response)
            assert response.status == 200, payload
            handed_out.append(payload["token"])
        in_memory = client.app[APP_CFG]["token"]
        on_disk = (tmp_path / "token.txt").read_text(encoding="utf-8").strip()

    assert in_memory == on_disk, (
        "the live credential and the token file diverged, so the next "
        "restart locks every client out")
    assert in_memory in handed_out, (
        "the surviving token was never handed to any caller")


def test_rotations_do_not_overlap_each_other(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Serialisation stated directly, because the race is probabilistic.

    `test_overlapping_rotations_leave_memory_and_disk_agreeing` asserts the
    outcome, and the outcome only diverges on unlucky interleavings -- it
    caught the unlocked code two runs in three. This one records when each
    rotation enters and leaves the executor and asserts the intervals do
    not overlap, which fails every time the lock is absent.
    """
    asyncio.run(_rotations_do_not_overlap(tmp_path, monkeypatch))


async def _rotations_do_not_overlap(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from arena.admin import handlers as admin_handlers

    real = admin_handlers.token_regenerate
    live = {"n": 0}
    overlaps: list[int] = []

    def slow(*args, **kwargs):
        live["n"] += 1
        if live["n"] > 1:
            overlaps.append(live["n"])
        time.sleep(0.05)
        try:
            return real(*args, **kwargs)
        finally:
            live["n"] -= 1

    monkeypatch.setattr(admin_handlers, "token_regenerate", slow)

    async with running_client(tmp_path, TOKEN) as client:
        from arena.app_keys import APP_CFG

        client.app[APP_CFG]["token_file"] = str(tmp_path / "token.txt")
        await asyncio.gather(*[
            client.post("/v1/token/regenerate", headers=auth_header(TOKEN))
            for _ in range(4)])

    assert not overlaps, (
        f"{len(overlaps)} rotation(s) ran while another was in flight; "
        "the write and the in-memory install are not serialised")


def test_the_rotation_lock_is_per_application(tmp_path: Path) -> None:
    """Two bridges in one process must not serialise against each other.

    The lock is stored on the aiohttp application rather than the module
    for this reason; a module-level lock would make the test rig's
    concurrent bridges contend and would be a real bottleneck for anyone
    running more than one.
    """
    from aiohttp import web

    from arena.admin.handlers import _rotation_lock_for

    first, second = web.Application(), web.Application()

    assert _rotation_lock_for(first) is _rotation_lock_for(first)
    assert _rotation_lock_for(first) is not _rotation_lock_for(second)


def test_the_200_schema_requires_the_note_the_handler_always_sends(
        ) -> None:
    """CodeRabbit: `note` is always returned, so the contract must say so.

    It is the field that tells an operator no restart is needed -- the
    correction #66 made -- so a generated client that drops it as optional
    loses the answer to the question people actually ask after rotating.
    """
    from unittest.mock import MagicMock

    from arena.public.openapi import build_openapi_spec

    schema = (build_openapi_spec(MagicMock())["paths"]["/v1/token/regenerate"]
              ["post"]["responses"]["200"]["content"]["application/json"]
              ["schema"])

    assert "note" in schema["properties"], schema
    assert schema["properties"]["note"]["type"] == "string", schema
    assert "note" in schema["required"], schema
