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
import os
from pathlib import Path

import pytest

from arena.exec.request_shape import (
    requested_command,
    unusable_command,
    unusable_shell_command,
)
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


# The separator that actually chains two commands, per shell. `cmd.exe`
# treats `;` as literal text -- `echo one; echo two` is a single `echo`
# printing "one; echo two", measured on the operator's Windows host. A
# test that asserted both words appeared would therefore pass without a
# second command ever running (cubic, CodeRabbit), which is the same
# false green this PR exists to remove.
CHAIN = "&" if os.name == "nt" else ";"


def test_chaining_two_commands_is_not_broken(tmp_path: Path) -> None:
    """Callers chain commands instead of using a newline, and must keep able to.

    The workaround agents were told to use is joining commands on one
    line. If this fix refused separators in general it would break every
    caller that took that advice, so the guard is about line breaks only.
    """
    asyncio.run(_chaining_still_works(tmp_path))


async def _chaining_still_works(tmp_path: Path) -> None:
    # A sentinel only the second command can print: the first echoes a
    # different word, so finding this one proves two executions rather
    # than one command that swallowed the separator as an argument.
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.post(
            "/v1/exec", headers=auth_header(TOKEN),
            json={"cmd": f"echo alpha{CHAIN} echo omega223", "timeout": 30})
        payload = await json_payload(response)

    assert response.status == 200, payload
    assert payload["ok"] is True, payload
    stdout = payload["stdout"]
    assert "alpha" in stdout, payload
    # Split assertions: the second is the one that proves the chaining,
    # and a composite would not say which half failed (SonarCloud).
    assert "omega223" in stdout, payload
    assert CHAIN not in stdout, payload


def test_the_separator_this_test_uses_really_chains() -> None:
    """The test above is only meaningful if `CHAIN` chains on this platform.

    Pinning it here means a wrong separator fails loudly instead of
    quietly turning `test_chaining_two_commands_is_not_broken` into an
    assertion about one `echo` printing its own arguments.
    """
    rc, stdout = asyncio.run(_shell_output(f"echo alpha{CHAIN} echo omega223"))
    assert rc == 0, stdout
    assert "omega223" in stdout
    assert CHAIN not in stdout, (
        f"{CHAIN!r} is literal text to this shell, not a separator: {stdout!r}")


async def _shell_output(command: str) -> tuple[int | None, str]:
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    return process.returncode, stdout.decode("utf-8", "replace")


@pytest.mark.parametrize("cmd", NEWLINE_COMMANDS)
def test_every_surface_agrees_on_what_a_newline_is(cmd: str) -> None:
    """The v2 API, the sandbox and the MCP tool refuse the same strings.

    They report a refusal differently -- JSON 400, JSON 400, `isError` --
    but the question is identical, so they ask one function. The first
    revision of this PR had them call `unusable_command` on the raw value
    while `/v1/exec` called it on the stripped one, which made
    `{"cmd": "echo hi\\n"}` a 400 on `/v1/sandbox` and a 200 on `/v1/exec`
    (cubic). One request must not mean two things depending on which
    endpoint it reaches, any more than on which OS it lands.
    """
    reason = unusable_shell_command(cmd, when_empty="unused")
    assert reason is not None
    assert reason == unusable_command(cmd.strip())


@pytest.mark.parametrize("cmd", ("echo hi\n", "\necho hi", "  echo hi  ", "echo hi"))
def test_no_surface_refuses_a_command_the_exec_endpoints_run(cmd: str) -> None:
    """The other half of the same agreement, from the accepting side."""
    assert unusable_shell_command(cmd, when_empty="unused") is None
    assert requested_command({"cmd": cmd})[1] is None


def test_an_empty_command_keeps_each_surface_its_own_wording() -> None:
    """Three endpoints have three established spellings of "you sent nothing".

    The helper answers the empty case with the caller's own text rather
    than inventing a fourth, so folding the check in changed no error
    message a client already depends on -- and left those handlers with
    one branch where they had two, which is how the CodeScene complexity
    finding was answered instead of suppressed.
    """
    for empty in ("", "   ", "\n", "  \r\n  "):
        assert unusable_shell_command(empty, when_empty="cmd is required") == "cmd is required"
    assert unusable_shell_command("", when_empty="missing 'cmd'") == "missing 'cmd'"


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
