"""Env gate for the exec endpoints: caller-supplied env names that control
what actually runs — command resolution, shell startup, dynamic loading —
must never override the child's environment, on POSIX or Windows. Covers
issue #64: mixed-case exact names, secret families, benign pass-through,
and the real handler composition (base ``os.environ`` plus filtered caller
overrides — the whole environment is never replaced).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.exec.environment import (  # noqa: E402
    _BLOCKED_ENV_EXACT,
    filter_caller_env,
)
from arena.exec.runner import run_shell_command  # noqa: E402


def compose_child_env(caller_env: dict) -> dict:
    """The exact composition the buffered and stream handlers perform."""
    env = os.environ.copy()
    env.update(filter_caller_env(caller_env))
    return env


def test_every_execution_control_name_is_blocked_under_mixed_case():
    mixed = {name.title(): "x" for name in _BLOCKED_ENV_EXACT}
    mixed.update({
        "Path": "x", "comspec": "x", "Ld_Preload": "x", "psModulePath": "x",
        "arena_token": "x", "appinit_dlls": "x", "bash_env": "x",
    })
    assert filter_caller_env(mixed) == {}


def test_windows_and_posix_names_from_the_issue_are_present():
    for name in (
        # Windows execution control
        "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
        "APPINIT_DLLS", "PSMODULEPATH", "AUTORUN",
        # POSIX execution control
        "IFS", "BASH_ENV", "ENV", "ZDOTDIR", "GIT_CONFIG_PARAMETERS", "GIT_SSH_COMMAND",
    ):
        assert name in _BLOCKED_ENV_EXACT, name


def test_user_data_locations_are_not_blocked_by_this_policy():
    # Where user data lives (TEMP, profile dirs) is a different invariant
    # from what runs; this denylist deliberately does not claim it.
    for name in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROMPT"):
        assert name not in _BLOCKED_ENV_EXACT, name


def test_secret_families_are_blocked_by_substring_in_any_case():
    blocked = {
        "MY_API_TOKEN": "x", "client_secret": "x", "DB_PASSWORD": "x",
        "SIGNING_KEY": "x", "STRIPE_CREDENTIAL": "x", "OpenAI_API_Key": "x",
    }
    assert filter_caller_env(blocked) == {}


def test_secret_family_false_positives_are_accepted_by_design():
    # Substring families over-block names like MONKEY and TOKENIZE rather
    # than risk missing a credential spelling: a caller who genuinely needs
    # such a name can rename it; a leaked token cannot be un-leaked.
    assert filter_caller_env({"MONKEY": "banana", "TOKENIZE": "mode"}) == {}


def test_benign_variables_pass_through_stringified():
    kept = filter_caller_env({"MY_VAR": 7, "LOG_LEVEL": "debug", "NO_COLOR": "1"})
    assert kept == {"MY_VAR": "7", "LOG_LEVEL": "debug", "NO_COLOR": "1"}


def test_blocked_names_cannot_override_the_child_environment(tmp_path):
    # The handler composition: base os.environ + filtered caller overrides.
    # Blocked names must keep the child's existing value (they are dropped
    # as overrides, not deleted from the base), benign names must apply.
    caller_env = {
        "PATH": "/definitely/not/real", "ComSpec": "attacker", "SYSTEMROOT": "x",
        "LD_PRELOAD": "/evil.so", "BASH_ENV": "/evil.sh", "PSMODULEPATH": "x",
        "MY_TOKEN": "leak-me", "MY_VAR": "benign-value",
    }
    child_env = compose_child_env(caller_env)

    # PATH exists in every real base environment; the caller's hijack must
    # not have replaced it.
    if "PATH" in os.environ:
        assert child_env["PATH"] == os.environ["PATH"]
    for name, malicious in caller_env.items():
        if name == "MY_VAR":
            continue
        assert child_env.get(name) != malicious, f"caller override of {name} survived the gate"
    assert child_env["MY_VAR"] == "benign-value"

    # End to end through the real runner with the composed environment: the
    # child sees the benign override, and inherits a working base env (this
    # is why the test never replaces the whole environment — on Windows a
    # child without SYSTEMROOT cannot even start a shell).
    cmd = f'"{sys.executable}" -c "import os; print(os.environ.get(\'MY_VAR\'))"'
    res = asyncio.run(run_shell_command(
        request_id="env-gate-test", cmd=cmd, cwd=tmp_path, env=child_env,
        timeout=30, max_output=10_000,
        decode_output_fn=lambda b: b.decode("utf-8", "replace"),
    ))
    assert res["ok"] is True, res
    assert res["stdout"].strip() == "benign-value"
