"""A newline in `cmd` must not be answered with `ok: true` (#223).

`POST /v1/exec {"cmd": "line one\\nline two"}` returned::

    {"ok": true, "exit_code": 0, "stdout": "<output of line one>",
     "stderr": ""}

and line two was **not executed**. Not queued, not failed, not reported --
dropped. Verified on the operator's Windows host by asking the tail to
create a file: the file was never created, and the response was still a
success.

The mechanism is the `cmd.exe /c "..."` wrapping, which ends the command
line at the first newline (the same family as #203). Measured on Windows
at this commit's parent::

    cmd /c echo first\\ncmd /c echo second   -> rc=0, stdout "first"
    powershell -Command "Write-Output 1\\nWrite-Output 2"
                                            -> rc=0, stdout "1"

Why nothing caught it. `_SHELL_CONTROL_CHARS` in `arena/security_commands.py`
does contain `\\n`, but it is read only by `command_allowlist_reason`, which
runs on the `cautious` profile. The default profile is `owner-shell`, which
does not call it, so the newline travelled to `create_subprocess_shell`
unexamined. `control_injection_response` runs earlier still and looks at
the control *lease*, not at the characters. `tests/test_exec_nul_cmd_288.py`
asserted the opposite in so many words -- that a newline "is refused
elsewhere, by the control-injection check, with a 403" -- which is why the
gap read as covered; that claim is corrected there.

The refusal is deliberately platform-independent even though a POSIX shell
would run the tail: one request must not mean two different things
depending on the operator's OS, and `POST /v1/exec/script` already takes a
multi-line script properly.

The bar this file holds is the one from the issue: never answer `ok: true`
for a command that was not executed as sent.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arena.exec.request_shape import requested_command, unusable_command
from tests._live_bridge import auth_header, json_payload, running_client

TOKEN = "exec-newline-cmd-token-223"

# Every spelling of "this command line has more than one line in it".
#
# Surrounding newlines are deliberately *not* here: `requested_command`
# calls `.strip()` before the guard, so "echo hi\n" is a single-line
# command with nothing after the newline to lose. Refusing it would break
# callers whose JSON serialiser adds a trailing newline, and it would be
# refusing a request that this defect does not affect. Pinned below by
# `test_a_command_wrapped_in_newlines_still_runs`.
NEWLINE_COMMANDS = (
    "echo one\necho two",
    "echo one\r\necho two",
    "echo one\rec ho two",
    "echo one\n\n\necho two",
    "  echo one\necho two  ",
    # The shape from the issue: the tail is the part that silently vanishes.
    "echo first\ncmd /c echo second",
)

EXEC_PATHS = ("/v1/exec", "/v1/exec/stream")


@pytest.mark.parametrize("cmd", NEWLINE_COMMANDS)
@pytest.mark.parametrize("path", EXEC_PATHS)
def test_a_newline_in_cmd_is_a_400(tmp_path: Path, path: str, cmd: str) -> None:
    """Both JSON exec endpoints read `cmd` alike and must refuse alike."""
    asyncio.run(_refusal_is_a_400(tmp_path, path, cmd))


async def _refusal_is_a_400(tmp_path: Path, path: str, cmd: str) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.post(
            path, headers=auth_header(TOKEN), json={"cmd": cmd, "timeout": 5})
        payload = await json_payload(response)

    assert response.status == 400, payload
    assert payload["ok"] is False, payload
    assert "newline" in payload["error"], payload


@pytest.mark.parametrize("cmd", NEWLINE_COMMANDS)
@pytest.mark.parametrize("path", EXEC_PATHS)
def test_the_refusal_never_reports_success(tmp_path: Path, path: str, cmd: str) -> None:
    """The defect, stated as the property that must hold.

    A 400 is one way to satisfy this; the thing that must never happen
    again is `ok: true` with `exit_code: 0` for a command line whose
    second half did not run. Asserting the property separately from the
    status code keeps the guarantee if the refusal is ever restyled.
    """
    asyncio.run(_never_ok_true(tmp_path, path, cmd))


async def _never_ok_true(tmp_path: Path, path: str, cmd: str) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.post(
            path, headers=auth_header(TOKEN), json={"cmd": cmd, "timeout": 5})
        payload = await json_payload(response)

    assert payload.get("ok") is not True, payload
    assert payload.get("exit_code") != 0, payload


def test_the_error_points_at_the_endpoint_that_works(tmp_path: Path) -> None:
    """A refusal that does not say what to do instead just moves the wall.

    `/v1/exec/script` takes a multi-line body and runs all of it, so the
    message names it. The issue asked for exactly this wording.
    """
    asyncio.run(_error_names_the_script_endpoint(tmp_path))


async def _error_names_the_script_endpoint(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.post(
            "/v1/exec", headers=auth_header(TOKEN),
            json={"cmd": "echo one\necho two", "timeout": 5})
        payload = await json_payload(response)

    assert "/v1/exec/script" in payload["error"], payload


def test_a_single_line_command_still_runs(tmp_path: Path) -> None:
    """The boundary from the other side: ordinary work is untouched."""
    asyncio.run(_a_real_command_runs(tmp_path))


async def _a_real_command_runs(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.post(
            "/v1/exec", headers=auth_header(TOKEN),
            json={"cmd": "echo hi", "timeout": 30})
        payload = await json_payload(response)

    assert response.status == 200, payload
    assert payload["ok"] is True, payload
    assert "hi" in payload["stdout"]


def test_the_documented_workaround_is_not_broken(tmp_path: Path) -> None:
    """`;` is how callers chain commands today, and must keep working.

    The obstacle registry tells agents to join with `;` instead of a
    newline. If this fix refused separators in general it would break
    every caller that took that advice, so the guard is about newlines
    only.
    """
    asyncio.run(_semicolon_still_chains(tmp_path))


async def _semicolon_still_chains(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.post(
            "/v1/exec", headers=auth_header(TOKEN),
            json={"cmd": "echo one; echo two", "timeout": 30})
        payload = await json_payload(response)

    assert response.status == 200, payload
    assert payload["ok"] is True, payload
    assert "one" in payload["stdout"] and "two" in payload["stdout"], payload


@pytest.mark.parametrize("cmd", NEWLINE_COMMANDS)
def test_the_guard_names_the_reason(cmd: str) -> None:
    """`unusable_command` answers with the reason, as it does for NUL."""
    reason = unusable_command(cmd)
    assert reason is not None
    assert "newline" in reason
    assert "/v1/exec/script" in reason


def test_the_body_reader_carries_the_refusal_through() -> None:
    """`requested_command` is what the handlers actually call.

    Checking `unusable_command` alone would leave the wiring untested --
    the parser can be right while the handler never asks it (#272).
    """
    cmd, unusable = requested_command({"cmd": "echo one\necho two"})
    assert cmd == "echo one\necho two"
    assert unusable is not None and "newline" in unusable


def test_a_command_wrapped_in_newlines_still_runs(tmp_path: Path) -> None:
    """A leading or trailing newline is whitespace, not a dropped tail.

    `.strip()` removes it before the guard looks, so nothing is lost and
    there is nothing to refuse. This is the line between "the request was
    only partly executed" (the defect) and "the request had whitespace
    around it" (not the defect), and it is drawn on purpose.
    """
    asyncio.run(_wrapped_command_runs(tmp_path))


async def _wrapped_command_runs(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        for cmd in ("echo hi\n", "\necho hi", "\n echo hi \n"):
            response = await client.post(
                "/v1/exec", headers=auth_header(TOKEN),
                json={"cmd": cmd, "timeout": 30})
            payload = await json_payload(response)
            assert response.status == 200, (cmd, payload)
            assert payload["ok"] is True, (cmd, payload)
            assert "hi" in payload["stdout"], (cmd, payload)


def test_a_command_that_only_has_a_newline_is_still_refused() -> None:
    """`.strip()` empties it, so it is refused as missing rather than run."""
    _, unusable = requested_command({"cmd": "\n"})
    assert unusable is not None


def test_single_line_commands_are_left_alone() -> None:
    """The guard is narrow: no newline, no opinion."""
    for cmd in ("echo hi", "echo one; echo two", "grep -r 'a b' .", "echo 'x\\ny'"):
        assert unusable_command(cmd) is None, cmd
