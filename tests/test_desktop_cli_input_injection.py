"""Desktop CLI input: coordinates and buttons are numbers, not shell text.

`arena/desktop/cli/input.py` scored top-4 on the danger-x-uncovered
ranking: it drives the mouse and keyboard of the host machine, and it was
at **0% coverage** -- not one line executed by the suite.

Bug #53. `click()` built its commands by interpolating raw argv into
shell strings:

    run(f'xdotool mousemove --sync {args.x} {args.y}', timeout=3)
    run(f'ydotool click {args.button}', timeout=3)

`--button` is declared as a plain string with no `choices`, so:

    --button "1; touch /tmp/PWNED"   ->  the file was created

`move()` happened to be safe for a reason worth noting: it runs `int()`
over its inputs before formatting them. That is the right instinct --
parsing beats escaping for values that are supposed to be numbers -- but
it was an accident of that one function rather than a rule, and it also
raised `ValueError` instead of answering, so a typo produced a traceback
instead of a message.

`key()` and `type_text()` were already careful (`shq`, or an argv list),
which is what made the gap in `click()` easy to miss.

Sabotage record (mandatory per AGENTS.md):
  1. dropping the `int(args.button)` conversion
     -> test_button_cannot_carry_a_shell_payload fails.
  2. dropping the `_MOUSE_BUTTONS` membership check
     -> test_button_must_be_a_real_mouse_button fails.
  3. formatting `args.x` instead of the parsed `x`
     -> test_coordinates_cannot_carry_a_shell_payload fails.
"""
from __future__ import annotations

import argparse

import pytest

from arena.desktop.cli import input as cli_input


class _Result:
    returncode = 0
    stderr = ""


@pytest.fixture()
def harness(monkeypatch):
    """Capture the command lines instead of driving a real desktop."""
    commands: list[str] = []
    answers: list[dict] = []

    monkeypatch.setattr(cli_input, "run",
                        lambda cmd, **kw: commands.append(cmd) or _Result())
    monkeypatch.setattr(cli_input, "have", lambda tool: tool == "ydotool")
    monkeypatch.setattr(cli_input, "ensure_ydotool", lambda: True)
    monkeypatch.setattr(cli_input, "_ensure_wm", lambda: None)
    monkeypatch.setattr(cli_input, "_focus_active_window", lambda: None)
    monkeypatch.setattr(cli_input, "j", answers.append)
    monkeypatch.setattr(cli_input.time, "sleep", lambda _s: None)
    return commands, answers


def _click(harness, x=5, y=5, button=1, steps=1, delay=0):
    """Invoke click() and return (commands issued, last JSON answer).

    A refusal calls sys.exit(1) after emitting its answer, which is the
    CLI's normal contract -- so SystemExit is expected, not a failure.
    """
    commands, answers = harness
    commands.clear()
    answers.clear()
    try:
        cli_input.click(argparse.Namespace(
            x=x, y=y, button=button, steps=steps, delay=delay))
    except SystemExit:
        pass
    return commands, (answers[-1] if answers else None)


# ---------------------------------------------------------------------------
# Injection.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "1; touch /tmp/arena-pwned",
    "1 && id",
    "1 | sh",
    "$(id)",
    "`id`",
    "1\nid",
    "1; rm -rf ~",
])
def test_button_cannot_carry_a_shell_payload(harness, payload):
    commands, answer = _click(harness, button=payload)

    assert answer is not None and answer["ok"] is False
    assert not any("touch" in c or "id" in c.split()[2:] for c in commands), (
        f"payload reached a command line: {commands}"
    )


@pytest.mark.parametrize("payload", [
    "5; touch /tmp/arena-pwned",
    "$(id)",
    "5 && id",
])
def test_coordinates_cannot_carry_a_shell_payload(harness, payload):
    for coords in ((payload, 5), (5, payload)):
        commands, answer = _click(harness, x=coords[0], y=coords[1])
        assert answer is not None and answer["ok"] is False
        assert not commands, f"a command ran with a bad coordinate: {commands}"


@pytest.mark.parametrize("button", [0, 6, 99, -1, 1000])
def test_button_must_be_a_real_mouse_button(harness, button):
    """Out-of-range is refused even though it cannot inject.

    ydotool interprets unknown button numbers unpredictably; refusing is
    both safer and a clearer error than whatever the tool does with 99.
    """
    _commands, answer = _click(harness, button=button)

    assert answer is not None and answer["ok"] is False
    assert "must be one of" in answer["error"]


# ---------------------------------------------------------------------------
# The tool still has to work.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("button", [1, 2, 3, 4, 5])
def test_every_real_button_still_clicks(harness, button):
    commands, answer = _click(harness, button=button)

    assert answer is not None and answer["ok"] is True
    assert answer["button"] == button
    assert f"ydotool click {button}" in commands


def test_a_string_digit_is_accepted(harness):
    """argparse hands over strings; `--button 3` must work."""
    _commands, answer = _click(harness, button="3")

    assert answer is not None and answer["ok"] is True
    assert answer["button"] == 3


def test_coordinates_reach_the_command_as_integers(harness):
    commands, answer = _click(harness, x="120", y="340", button=1)

    assert answer["ok"] is True
    moves = [c for c in commands if "mousemove" in c]
    assert moves, "no mouse movement was issued"
    assert all("120" not in c or "-x" in c or "--sync" in c for c in moves)


# ---------------------------------------------------------------------------
# move(): safe by parsing, but it must answer rather than crash.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["abc", "5; id", None, "", "1.5.2"])
def test_move_refuses_non_numeric_input_without_a_traceback(harness, bad):
    commands, answers = harness
    commands.clear()
    answers.clear()

    try:
        cli_input.move(argparse.Namespace(x=bad, y=5, steps=1, delay=0))
    except SystemExit:
        pass
    except Exception as exc:  # pragma: no cover - this is the failure
        pytest.fail(f"move() raised {type(exc).__name__} instead of answering: {exc}")

    assert answers and answers[-1]["ok"] is False
    assert not commands


def test_move_still_moves(harness):
    commands, answers = harness
    commands.clear()
    answers.clear()

    cli_input.move(argparse.Namespace(x=10, y=20, steps=2, delay=0))

    assert answers[-1]["ok"] is True
    assert len([c for c in commands if "mousemove" in c]) == 2


# ---------------------------------------------------------------------------
# Ratchet over the whole module.
# ---------------------------------------------------------------------------

def test_no_argv_value_is_interpolated_into_a_shell_string():
    """Catch the next `f'tool {args.something}'` before it ships.

    `key()` and `type_text()` already route through `shq()` or an argv
    list; this asserts nobody adds a third pattern.
    """
    import pathlib
    import re

    source = pathlib.Path(cli_input.__file__).read_text(encoding="utf-8")
    offenders = []
    for lineno, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # f-string command lines that interpolate an `args.` attribute
        # directly, without shq() around it.
        if re.search(r"\{args\.\w+\}", stripped) and "shq(" not in stripped:
            offenders.append(f"{lineno}: {stripped}")

    assert not offenders, (
        "these lines drop an argv value straight into a shell command:\n"
        + "\n".join(offenders)
    )
