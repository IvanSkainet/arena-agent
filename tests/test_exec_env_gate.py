"""Env gate for the exec endpoints: caller-supplied env names that control
what actually runs — command resolution, shell startup, dynamic loading —
must never override the child's environment, on POSIX or Windows. Covers
issue #64: mixed-case exact names, secret families, benign pass-through,
and the real handler composition (base ``os.environ`` plus filtered caller
overrides — the whole environment is never replaced).

The expected exact denylist is defined HERE, independently of the product
module. The assertion against ``_BLOCKED_ENV_EXACT`` is equality in both
directions, so deleting OR adding a name on the product side fails this
suite: the historical bug was a test that derived its input from the
production set, which made any product-side deletion silently unobservable.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from arena.exec.environment import (  # noqa: E402
    _BLOCKED_ENV_EXACT,
    _BLOCKED_ENV_SUBSTRINGS,
    filter_caller_env,
)
from arena.exec.runner import run_shell_command  # noqa: E402

# Independent fixture: the COMPLETE expected exact denylist, including the
# ten names that survived mutation at 654b6209 (ARENA_TOKEN, SHELL,
# LD_LIBRARY_PATH, LD_AUDIT, LD_DEBUG, PYTHONPATH, PYTHONSTARTUP,
# PYTHONHOME, GIT_CONFIG, DYLD_FRAMEWORK_PATH). Every production entry must
# appear here; anything missing makes the equality test red.
EXPECTED_EXACT = frozenset({
    # The bridge's own credential: a caller must not be able to override
    # or shadow it for a spawned command.
    "ARENA_TOKEN",
    # POSIX execution control: dynamic loading, shell startup, interpreter
    # and git behavior.
    "PATH", "IFS", "SHELL", "ENV", "BASH_ENV", "ZDOTDIR",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG",
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_SSH_COMMAND",
    # macOS execution control: the DYLD_* family is the counterpart of
    # LD_PRELOAD / LD_LIBRARY_PATH on Darwin.
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    # Windows execution control: interpreter and shell selection, DLL
    # preload, module path, cmd AutoRun.
    "PATHEXT", "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "APPINIT_DLLS", "PSMODULEPATH", "AUTORUN",
})

# Independent fixture for the substring families: dropping one here must
# fail the equality test, and the secret-family tests kill it a second way.
EXPECTED_SUBSTRINGS = ("TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL", "BASH_FUNC_")


def compose_child_env(caller_env: dict) -> dict:
    """The exact composition the buffered and stream handlers perform."""
    env = os.environ.copy()
    env.update(filter_caller_env(caller_env))
    return env


def test_expected_denylist_matches_product_exactly():
    # Equality in both directions: a name missing from the product set, or
    # an extra name the policy never claimed, both fail here.
    assert _BLOCKED_ENV_EXACT == EXPECTED_EXACT


def test_expected_substring_families_match_product_exactly():
    assert _BLOCKED_ENV_SUBSTRINGS == EXPECTED_SUBSTRINGS


def test_windows_and_posix_names_from_the_issue_are_present():
    # The exact vectors from issue #64 must be part of the pinned contract.
    for name in (
        # Windows execution control
        "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
        "APPINIT_DLLS", "PSMODULEPATH", "AUTORUN",
        # POSIX execution control
        "IFS", "BASH_ENV", "ENV", "ZDOTDIR", "GIT_CONFIG_PARAMETERS", "GIT_SSH_COMMAND",
        # macOS execution control (DYLD_* is the LD_PRELOAD counterpart on Darwin)
        "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
    ):
        assert name in EXPECTED_EXACT, name


@pytest.mark.parametrize("name", sorted(EXPECTED_EXACT))
def test_every_execution_control_name_is_blocked_under_mixed_case(name):
    # Each pinned name must be dropped in every casing a caller could use.
    for mixed in (name.lower(), name.title(), name.swapcase()):
        assert filter_caller_env({mixed: "x"}) == {}, f"{mixed} survived the gate"


def test_all_execution_control_names_blocked_together_in_mixed_case():
    mixed = {name.title(): "x" for name in EXPECTED_EXACT}
    mixed.update({
        "Path": "x", "comspec": "x", "Ld_Preload": "x", "psModulePath": "x",
        "arena_token": "x", "appinit_dlls": "x", "bash_env": "x",
    })
    assert filter_caller_env(mixed) == {}


def test_user_data_locations_are_not_blocked_by_this_policy():
    # Where user data lives (TEMP, profile dirs) is a different invariant
    # from what runs; this denylist deliberately does not claim it. This is
    # the over-block sabotage direction: adding a user-data name to the
    # exact denylist must fail these assertions.
    for name in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROMPT"):
        assert name not in _BLOCKED_ENV_EXACT, name
    kept = filter_caller_env({name: "x" for name in (
        "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROMPT")})
    assert kept == {
        "TEMP": "x", "TMP": "x", "APPDATA": "x",
        "LOCALAPPDATA": "x", "USERPROFILE": "x", "PROMPT": "x",
    }


def test_secret_families_are_blocked_by_substring_in_any_case():
    blocked = {
        "MY_API_TOKEN": "x", "client_secret": "x", "DB_PASSWORD": "x",
        "SIGNING_KEY": "x", "STRIPE_CREDENTIAL": "x", "OpenAI_API_Key": "x",
    }
    assert filter_caller_env(blocked) == {}


def test_macos_and_shell_function_injection_vectors_are_blocked():
    # DYLD_* is the macOS counterpart of LD_PRELOAD; BASH_FUNC_-prefixed
    # names smuggle exported shell functions into the child shell.
    assert filter_caller_env({"DYLD_INSERT_LIBRARIES": "/evil.dylib"}) == {}
    assert filter_caller_env({"dyld_library_path": "/evil/lib"}) == {}
    assert filter_caller_env({"BASH_FUNC_steal%%": "() { id; }"}) == {}


def test_secret_family_false_positives_are_accepted_by_design():
    # Substring families over-block names like MONKEY and TOKENIZE rather
    # than risk missing a credential spelling: a caller who genuinely needs
    # such a name can rename it; a leaked token cannot be un-leaked.
    assert filter_caller_env({"MONKEY": "banana", "TOKENIZE": "mode"}) == {}


def test_benign_variables_pass_through_stringified():
    kept = filter_caller_env({"MY_VAR": 7, "LOG_LEVEL": "debug", "NO_COLOR": "1"})
    assert kept == {"MY_VAR": "7", "LOG_LEVEL": "debug", "NO_COLOR": "1"}


def test_non_string_keys_are_stringified():
    # A caller-controlled env map can carry non-string keys; they must be
    # normalized before reaching the child environment (this also pins the
    # str(key) call, which purely-string inputs cannot observe).
    assert filter_caller_env({1: "x", 2.5: "y"}) == {"1": "x", "2.5": "y"}


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
