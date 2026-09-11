"""A NUL in `cmd` is the caller's mistake, not a 500 (#288).

Found by the #258 fuzzing gate on an unrelated PR: a command line carrying
an embedded NUL reached `subprocess`, which cannot pass one through
`execve` and says so with `ValueError: embedded null byte`. The exception
arrives from the spawn, well after the handler has approved the request,
so it left as::

    POST /v1/exec  {"cmd": "echo\\u0000hi"}
      -> 500 {"ok": false, "error": "Internal error"}

`cwd` has been guarded since #270 -- `usable_cwd` refuses a NUL before the
boundary check, because a string with a NUL in it is not a path at all.
`cmd` reaches the same syscall by the same route and had no such guard,
which is the whole of the defect.

Two halves here, as in #270: both JSON exec endpoints answer 400, and the
audit journal never sees the NUL, since a raw NUL in a log line is what
turns a bad request into a corrupt record downstream.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from arena.exec.request_shape import unusable_command
from tests._live_bridge import auth_header, json_payload, running_client

TOKEN = "exec-nul-cmd-token-288"

# Where a NUL can sit in a command line. The trailing one matters on its
# own: `.strip()` runs before the guard and does not remove NULs, so a
# command that looks clean to a human is still unspawnable.
NUL_COMMANDS = (
    "\x00",
    "echo\x00hi",
    "echo hi\x00",
    "\x00echo hi",
    "·\r\xba\x00\xdd",  # the shape the fuzzer actually generated
)

# A lone surrogate is the other thing a JSON body can carry and `execve`
# cannot: `create_subprocess_shell` raises `UnicodeEncodeError` encoding
# the argument, which was the same 500 by another route (cubic).
SURROGATE_COMMANDS = ("\udb72", "echo \udb72x", "\udc05 hi")

EXEC_PATHS = ("/v1/exec", "/v1/exec/stream")


@pytest.mark.parametrize("cmd", NUL_COMMANDS + SURROGATE_COMMANDS)
@pytest.mark.parametrize("path", EXEC_PATHS)
def test_a_nul_in_cmd_is_a_400(tmp_path: Path, path: str, cmd: str) -> None:
    """Both JSON exec endpoints read `cmd` the same way and must refuse alike."""
    asyncio.run(_refusal_is_a_400(tmp_path, path, cmd))


async def _refusal_is_a_400(tmp_path: Path, path: str, cmd: str) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.post(
            path, headers=auth_header(TOKEN), json={"cmd": cmd, "timeout": 5})
        payload = await json_payload(response)

    assert response.status == 400, payload
    assert payload["ok"] is False
    assert "not a usable command" in payload["error"], payload


def test_the_audit_journal_never_receives_the_nul(tmp_path: Path) -> None:
    """A raw NUL in a log line corrupts the record for everything downstream.

    The refusal is placed before the audit call for this reason, so the
    journal holds nothing at all about the request rather than an entry
    that `grep` and `jq` both choke on.
    """
    asyncio.run(_journal_stays_clean(tmp_path))


async def _journal_stays_clean(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.post(
            "/v1/exec", headers=auth_header(TOKEN),
            json={"cmd": "echo\x00hi", "timeout": 5})
        assert response.status == 400

    for journal in tmp_path.rglob("*"):
        if journal.is_file():
            assert "\x00" not in journal.read_text(encoding="utf-8", errors="replace")


def test_a_command_without_a_nul_still_runs(tmp_path: Path) -> None:
    """The boundary from the other side: the guard must not refuse real work."""
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


@pytest.mark.parametrize("cmd", NUL_COMMANDS + SURROGATE_COMMANDS)
def test_the_guard_names_the_reason(cmd: str) -> None:
    """`unusable_command` answers with the reason, mirroring `usable_cwd`."""
    reason = unusable_command(cmd)
    assert reason is not None
    assert "not a usable command" in reason


def test_an_ordinary_command_is_not_refused() -> None:
    """The guard must not refuse a command line that spawns fine.

    This test used to also assert `unusable_command("echo\\nhi") is None`,
    on the stated grounds that "a newline or a carriage return in `cmd`
    is refused elsewhere, by the control-injection check, with a 403 that
    says so". That was not true of the code: `control_injection_error`
    consults the *control lease* (halted / paused / revoked) and only then
    matches desktop-input injection -- it never looks at shell control
    characters. `_SHELL_CONTROL_CHARS` does contain `\\n`, but it is read
    only by `command_allowlist_reason`, which the `owner-shell` profile
    does not call. So on the default profile a newline reached the shell
    unchecked, and on Windows the tail after it was silently dropped
    (#223). The newline case now lives in
    `tests/test_exec_newline_cmd_223.py`.
    """
    assert unusable_command("echo hi") is None
    assert unusable_command("echo one; echo two") is None


def test_the_body_a_client_sends_is_the_body_that_is_refused() -> None:
    """A NUL survives JSON, which is why the endpoint can be reached at all.

    `json.dumps` escapes it to `\\u0000` and every decoder returns it as a
    character, so this is a request a well-behaved HTTP client can send by
    accident -- not a malformed one the parser would have caught.
    """
    encoded = json.dumps({"cmd": "echo\x00hi"})
    assert "\\u0000" in encoded
    assert json.loads(encoded)["cmd"] == "echo\x00hi"
