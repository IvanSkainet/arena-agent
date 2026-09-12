"""What `write_owner_token` promises once `os.replace` has run (#211).

The status fix in `test_token_regenerate_status_211.py` rests on the
storage primitive answering one question honestly: after the rename, is
the new token what the file holds? Three answers are possible and they
are not interchangeable, because a caller decides on them whether to keep
the new credential in memory:

* yes, and the mode is set -- an ordinary success;
* yes, but the mode could not be re-applied -- `TokenFileModeWarning`.
  Raising a plain error here is what #211 was reported for from the other
  direction: the caller kept the old credential while the next restart
  read the new one off disk, locking every client out;
* no, the path was removed or swapped by someone else --
  `TokenFileVanishedError`, a hard failure even when the mode change
  itself succeeded.

Bootstrap's first-start generation lives here too, since it is the other
caller of the same primitive and has to make the same distinction.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from arena import token_storage
from tests._live_bridge import auth_header, json_payload, running_client
from tests.test_token_regenerate_status_211 import (
    TOKEN,
    _failed_rotation_is_a_500,
    _write_tokens_under,
)

# ---------------------------------------------------------------------------
# The chmod-after-replace window (cubic, P1)
# ---------------------------------------------------------------------------
# `write_owner_token` chmods the temporary file by path, calls
# `os.replace`, then re-applies the mode. On POSIX that second call goes
# through the descriptor it kept open (`os.fchmod`, so a swapped path
# cannot redirect it); elsewhere the file cannot stay open across a
# rename, so it is `os.chmod` on the target. These helpers hook whichever
# one the platform actually uses -- patching only `os.fchmod` made all of
# these tests fail on the five windows-latest jobs while passing locally.
_POST_REPLACE_CALL = "fchmod" if os.name == "posix" else "chmod"


def _is_the_post_replace_call(first_argument, target: Path) -> bool:
    """Is this the mode change that happens after the rename?

    On POSIX the call takes the descriptor, and there is exactly one
    `os.fchmod` in the write, so any call qualifies. On the path-based
    side both the temporary file and the target go through `os.chmod`, so
    only a call naming the target counts.
    """
    if _POST_REPLACE_CALL == "fchmod":
        return True
    return Path(first_argument) == target


def _mode_change_that_fails_after_the_replace(monkeypatch, target: Path):
    """Let the pre-replace chmod through, fail the post-replace one.

    Only the second call is past the point of no return, so only it is
    made to fail.
    """
    real = getattr(token_storage.os, _POST_REPLACE_CALL)

    def denied(first, mode, *args, **kwargs):
        if _is_the_post_replace_call(first, target):
            raise PermissionError("chmod after replace failed")
        return real(first, mode, *args, **kwargs)

    monkeypatch.setattr(token_storage.os, _POST_REPLACE_CALL, denied)


def _after_the_replace(monkeypatch, target: Path, tamper):
    """Run `tamper()` at the post-replace mode change, then succeed.

    Used to model another process reaching the path in the window the
    identity check guards, with the mode change itself working fine.
    """
    real = getattr(token_storage.os, _POST_REPLACE_CALL)

    def meddles(first, mode, *args, **kwargs):
        result = real(first, mode, *args, **kwargs)
        if _is_the_post_replace_call(first, target):
            tamper()
        return result

    monkeypatch.setattr(token_storage.os, _POST_REPLACE_CALL, meddles)


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
    _mode_change_that_fails_after_the_replace(monkeypatch, target)

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
        _mode_change_that_fails_after_the_replace(monkeypatch, target)

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
    _mode_change_that_fails_after_the_replace(monkeypatch, target)
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
    _after_the_replace(monkeypatch, target, lambda: os.replace(intruder, target))

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
    _after_the_replace(monkeypatch, target, lambda: os.unlink(target))

    assert not issubclass(
        token_storage.TokenFileVanishedError, token_storage.TokenFileModeWarning)
    with pytest.raises(token_storage.TokenFileVanishedError):
        token_storage.write_owner_token(target, "NEW-TOKEN")


def test_the_bridge_does_not_start_on_a_token_that_vanished(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """First start tolerates the mode warning, not a disappeared file."""
    from arena.bootstrap_token import resolve_token

    target = tmp_path / "token.txt"
    _after_the_replace(monkeypatch, target, lambda: os.unlink(target))
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

    _after_the_replace(monkeypatch, victim, unlink_the_token)
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
