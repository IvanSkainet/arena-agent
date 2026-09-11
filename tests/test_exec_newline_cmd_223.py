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
import json
import os
from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request

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


# Every surface that reads `cmd` itself and shells it, reached through its
# real entry point. An earlier revision called `unusable_shell_command`
# from each module's namespace, which proved only that the import existed:
# a handler that kept the import and stopped calling it would still have
# passed (cubic). These go through the handler.
def _sandbox_refusal(cmd: object) -> str | None:
    return asyncio.run(_sandbox_response(cmd))


async def _sandbox_response(cmd: object) -> str | None:
    import unified_bridge as ub
    from arena.handler_context import SandboxHandlerContext
    from arena.sandbox.handlers import make_sandbox_handlers

    ctx = SandboxHandlerContext(
        require_auth=lambda *a, **k: None,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        blocked_reason=ub.blocked_reason,
        first_word=ub.first_word,
        run_sandboxed=_must_not_run,
        audit=ub.audit,
        emit_event=ub.emit_event,
    )
    handler = make_sandbox_handlers(ctx).sandbox
    request = make_mocked_request("POST", "/v1/sandbox")
    body = json.dumps({"action": "run", "cmd": cmd, "timeout": 5}).encode()
    request.read = _returns(body)  # type: ignore[method-assign]
    return _error_of(await handler(request))


def _api_v2_refusal(cmd: object) -> str | None:
    return asyncio.run(_api_v2_response(cmd))


async def _api_v2_response(cmd: object) -> str | None:
    import unified_bridge as ub
    from arena.api_v2.exec_handler import make_v2_exec_handler
    from arena.handler_context import ApiV2HandlerContext

    ctx = ApiV2HandlerContext(
        require_auth=lambda *a, **k: None,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        version=ub.VERSION,
        metrics=ub.BRIDGE_METRICS,
        cdp_state=ub._cdp_state,
        watchdog_state=ub._watchdog_state,
        cluster_state=ub._cluster_state,
        cluster_config=ub._cluster_config,
        tls_config=ub._tls_config,
        profiles_dir=Path("."),
        sandbox_config=ub._sandbox_config,
        blocked_reason=ub.blocked_reason,
        first_word=ub.first_word,
        decode_output=ub.decode_output,
        run_sandboxed=_must_not_run,
        cfg_get_max_timeout=lambda request: 60,
        audit=ub.audit,
        emit_event=ub.emit_event,
        now=lambda: ub.BRIDGE_METRICS["start_time"] + 1.25,
    )
    handler = make_v2_exec_handler(ctx)
    request = make_mocked_request("POST", "/v2/exec")
    request.read = _returns(json.dumps({"cmd": cmd, "timeout": 5}).encode())  # type: ignore[method-assign]
    return _error_of(await handler(request))


def _mcp_refusal(cmd: object) -> str | None:
    import unified_bridge as ub
    from arena.mcp.tool_exec import handle_exec_tool

    class _Ctx:
        blocked_reason = staticmethod(ub.blocked_reason)
        first_word = staticmethod(ub.first_word)
        cautious_allow = ub._sandbox_config["allowed_commands"]

        @staticmethod
        def app_config() -> dict:
            return {"profile": "owner-shell"}

    result = handle_exec_tool(
        "exec.exec", {"cmd": cmd}, ctx=_Ctx(), run_sd=_must_not_run)
    assert result is not None
    if not result.get("isError"):
        return None
    return str(result["content"][0]["text"])


def _must_not_run(*args: object, **kwargs: object) -> None:
    """The whole point is that the command never reaches a shell."""
    raise AssertionError(f"the command was executed: {args!r} {kwargs!r}")


def _returns(payload: bytes):
    async def read() -> bytes:
        return payload
    return read


def _error_of(response: object) -> str | None:
    """The refusal text an aiohttp response carries, or None if it ran."""
    body = json.loads(getattr(response, "body", b"{}") or b"{}")
    if body.get("ok") is False:
        return str(body.get("error", ""))
    return None


SURFACES = (_sandbox_refusal, _api_v2_refusal, _mcp_refusal)


@pytest.mark.parametrize("surface", SURFACES, ids=["sandbox", "api_v2", "mcp"])
@pytest.mark.parametrize("cmd", NEWLINE_COMMANDS)
def test_every_surface_refuses_an_embedded_newline(surface, cmd: str) -> None:
    """The v2 API, the sandbox and the MCP tool refuse what /v1/exec refuses.

    `run_sandboxed` and `run_sd` raise if called, so a surface that lets
    the command through fails here rather than quietly shelling it.
    """
    reason = surface(cmd)
    assert reason is not None
    assert "newline" in reason


@pytest.mark.parametrize("surface", SURFACES, ids=["sandbox", "api_v2", "mcp"])
@pytest.mark.parametrize("cmd", (None, 0, False, []))
def test_no_surface_shells_a_body_that_names_no_command(surface, cmd: object) -> None:
    """`{"cmd": null}` must not become the command line `None` (cubic).

    Each surface used to answer this with its own `if not cmd:`. Folding
    that into the shared helper briefly moved the `str()` conversion in
    front of the check, which turned these bodies into the literal
    commands "None", "0" and "False" -- executed, and reported as a
    success.
    """
    reason = surface(cmd)
    assert reason is not None
    assert "newline" not in reason  # named as missing, not as malformed


@pytest.mark.parametrize("cmd", (None, 0, False, []))
@pytest.mark.parametrize("path", EXEC_PATHS)
def test_the_exec_endpoints_do_not_shell_a_falsy_cmd(
        tmp_path: Path, path: str, cmd: object) -> None:
    """The same, for the two endpoints the issue is actually about.

    `requested_command` stringified before its own empty check, so
    `{"cmd": null}` reached the shell as `None` on `/v1/exec` itself while
    the three surfaces above already refused it -- the inconsistency this
    PR set out to remove, surviving in the primary path (cubic).
    """
    asyncio.run(_falsy_cmd_is_refused(tmp_path, path, cmd))


async def _falsy_cmd_is_refused(tmp_path: Path, path: str, cmd: object) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.post(
            path, headers=auth_header(TOKEN), json={"cmd": cmd, "timeout": 5})
        payload = await json_payload(response)

    assert response.status == 400, payload
    assert payload["ok"] is False, payload
    assert payload["error"] == "missing cmd", payload


@pytest.mark.parametrize("cmd", ("echo hi\n", "\necho hi", "  echo hi  "))
def test_the_surfaces_accept_what_the_exec_endpoints_accept(cmd: str) -> None:
    """The concrete cross-surface agreement, stated as behaviour.

    An earlier revision asserted
    `unusable_shell_command(cmd) == unusable_command(cmd.strip())`, which
    is true by the helper's own definition and so could not fail (cubic --
    the same trap as the `round(0.6) == 1` test on #272). What needs
    pinning is that a body `/v1/exec` accepts is not refused elsewhere:
    the first revision of this PR returned 400 for `{"cmd": "echo hi\\n"}`
    on those three while `/v1/exec` returned 200.
    """
    assert unusable_shell_command(cmd, when_empty="unused") is None
    assert requested_command({"cmd": cmd})[1] is None


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
