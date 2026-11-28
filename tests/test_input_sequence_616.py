"""Timed input sequences: held keys, relative motion, one call (#616, #617)."""
# `desktop.key` presses and releases in one call and `desktop.mouse` only
# teleports the cursor, so an agent could not hold a key, turn a camera or time
# two actions against each other. `POST /v1/desktop/sequence` runs a list of
# steps on the host. These tests pin the properties that make that safe to
# hand to an agent:
#
# * a bad step is refused before anything is pressed;
# * whatever was pressed is released, however the sequence ends;
# * the sequence names its window and stops when another one is in front;
# * a paused control lease stops it in the middle.
#
# Nothing here sends real input: the driver is a recorder, and the Windows
# driver is given a stand-in for user32.

from __future__ import annotations

import pytest

from arena.desktop.input_sequence import (
    MAX_HOLD_MS,
    MAX_STEPS,
    MAX_TOTAL_MS,
    Guard,
    SequenceError,
    plan_sequence,
    planned_duration_ms,
)
from tests._input_sequence_support import TITLE, Clock, Recorder, run


# ---------------------------------------------------------------------
# 1. the plan: refused before anything is pressed
# ---------------------------------------------------------------------
@pytest.mark.parametrize(("steps", "fragment"), [
    (None, "non-empty list"),
    ([], "non-empty list"),
    ([{"do": "wait", "ms": 1}] * (MAX_STEPS + 1), "at most"),
    (["tap"], "must be an object"),
    ([{"do": "explode"}], "'do' must be one of"),
    ([{"do": "tap"}], "'key' must be a key name"),
    ([{"do": "tap", "key": "hyper"}], "unknown key 'hyper'"),
    ([{"do": "click", "button": "fourth"}], "'button' must be one of"),
    ([{"do": "wait"}], "'ms' must be an integer"),
    ([{"do": "wait", "ms": True}], "'ms' must be an integer"),
    ([{"do": "wait", "ms": -1}], "between 0 and"),
    ([{"do": "tap", "key": "w", "ms": MAX_HOLD_MS + 1}], "between 1 and"),
    ([{"do": "move", "dx": 1.5}], "'dx' must be an integer"),
    ([{"do": "move_to", "x": 1}], "'y' must be an integer"),
    ([{"do": "scroll", "clicks": 1000}], "between -100 and 100"),
])
def test_a_bad_step_is_refused_with_its_reason(steps, fragment):
    driver = Recorder()
    with pytest.raises(SequenceError, match=fragment):
        plan_sequence(steps, driver)


def test_the_refusal_names_the_step():
    driver = Recorder()
    with pytest.raises(SequenceError) as caught:
        plan_sequence([{"do": "wait", "ms": 1}, {"do": "tap", "key": "hyper"}], driver)
    assert caught.value.index == 1


def test_a_sequence_longer_than_the_limit_is_refused():
    steps = [{"do": "wait", "ms": MAX_TOTAL_MS // 2}] * 3
    driver = Recorder()
    with pytest.raises(SequenceError, match="the limit is"):
        plan_sequence(steps, driver)


def test_a_key_held_past_the_limit_is_refused():
    """Found by adding up the waits between the press and the release."""
    steps = [{"do": "key_down", "key": "w"}, {"do": "wait", "ms": 9_000},
             {"do": "wait", "ms": 9_000}, {"do": "key_up", "key": "w"}]
    driver = Recorder()
    with pytest.raises(SequenceError, match="key:w would stay down longer"):
        plan_sequence(steps, driver)


def test_a_button_never_released_counts_as_held_to_the_end():
    steps = [{"do": "mouse_down"}, {"do": "wait", "ms": MAX_HOLD_MS + 1}]
    driver = Recorder()
    with pytest.raises(SequenceError, match="button:left would stay down longer"):
        plan_sequence(steps, driver)


def test_a_hold_released_in_time_is_accepted_and_names_are_normalised():
    steps = [{"do": "key_down", "key": " W "}, {"do": "wait", "ms": MAX_HOLD_MS}, {"do": "key_up", "key": "w"}]
    planned = plan_sequence(steps, Recorder())
    assert planned[0] == {"do": "key_down", "key": "w"}
    assert planned_duration_ms(planned) == MAX_HOLD_MS


# ---------------------------------------------------------------------
# 2. the run
# ---------------------------------------------------------------------
def test_two_actions_are_timed_against_each_other():
    """The case from the issue: hold jump, 280 ms later right-click, let go."""
    result, driver, clock = run([
        {"do": "key_down", "key": "space"}, {"do": "wait", "ms": 280},
        {"do": "click", "button": "right", "ms": 50}, {"do": "key_up", "key": "space"},
    ])
    assert driver.events == [
        ("key_down", "space"), ("button_down", "right"), ("button_up", "right"), ("key_up", "space")]
    assert result["ok"] is True
    assert result["steps_done"] == result["steps_total"] == 4
    assert result["elapsed_ms"] == 330 == round(clock.now * 1000)
    assert result["released_at_end"] == {"keys": [], "buttons": []}


def test_what_the_caller_forgot_to_release_is_released():
    result, driver, _ = run([
        {"do": "key_down", "key": "shift"}, {"do": "key_down", "key": "w"}, {"do": "mouse_down"},
        {"do": "wait", "ms": 100},
    ])
    assert result["ok"] is True
    assert result["released_at_end"] == {"keys": ["w", "shift"], "buttons": ["left"]}
    assert driver.events[-3:] == [("button_up", "left"), ("key_up", "w"), ("key_up", "shift")]


def test_another_window_in_front_stops_the_sequence_before_it_starts():
    result, driver, _ = run([{"do": "tap", "key": "w"}], Recorder(title="Terminal"))
    assert driver.events == []
    assert result["ok"] is False
    assert result["error"] == "input_guard_failed"
    assert result["active_title"] == "Terminal"
    assert result["steps_done"] == 0


def test_a_window_change_during_a_hold_releases_the_key():
    driver, clock = Recorder(), Clock()

    def lose_focus(now: float) -> None:
        if now >= 0.2:
            driver.title = "Save changes?"

    clock.on_sleep = lose_focus
    result, _, _ = run([{"do": "key_down", "key": "w"}, {"do": "wait", "ms": 5_000},
                         {"do": "key_up", "key": "w"}, {"do": "tap", "key": "space"}], driver, clock=clock)
    assert driver.events == [("key_down", "w"), ("key_up", "w")]
    assert result["error"] == "input_guard_failed"
    assert result["steps_done"] == 1
    assert result["released_at_end"] == {"keys": ["w"], "buttons": []}
    assert result["elapsed_ms"] < 400


def test_the_title_match_ignores_case():
    result, _, _ = run([{"do": "tap", "key": "w"}], Recorder(title="MY GAME"), guard=Guard("my game"))
    assert result["ok"] is True


def test_a_paused_lease_stops_the_sequence_in_the_bridge_s_own_words():
    clock = Clock()
    paused = {"ok": False, "error": "control_paused", "message": "Agent desktop control is paused by user",
              "status": "paused", "reason": "hands off"}
    result, driver, _ = run(
        [{"do": "mouse_down"}, {"do": "wait", "ms": 3_000}, {"do": "mouse_up"}],
        clock=clock, guard=Guard(TITLE, lambda: paused if clock.now >= 1.0 else None))
    assert driver.events == [("button_down", "left"), ("button_up", "left")]
    assert result["ok"] is False
    assert result["error"] == "control_paused"
    assert result["reason"] == "hands off"
    assert result["released_at_end"] == {"keys": [], "buttons": ["left"]}


def test_an_input_the_system_refuses_is_reported_and_the_rest_is_released():
    driver = Recorder()
    driver.fail_on = "move_rel"
    result, _, _ = run([{"do": "key_down", "key": "w"}, {"do": "move", "dx": 10}], driver)
    assert result["ok"] is False
    assert result["error"] == "input_failed"
    assert "SendInput" in result["message"]
    assert driver.events == [("key_down", "w"), ("key_up", "w")]


def test_one_failed_release_does_not_strand_the_others():
    class StickyShift(Recorder):
        def key_up(self, name):
            if name == "shift":
                raise OSError("blocked")
            super().key_up(name)

    result, driver, _ = run([{"do": "key_down", "key": "w"}, {"do": "key_down", "key": "shift"}], StickyShift())
    assert ("key_up", "w") in driver.events
    assert result["released_at_end"] == {"keys": ["w"], "buttons": []}
    # A key the system would not let go is still down for the user: the result says which.
    assert result["ok"] is False
    assert result["error"] == "input_failed"
    assert result["release_failed"] == ["key:shift"]
    assert "key:shift" in result["message"]


def test_a_move_without_a_duration_is_one_event():
    _, driver, clock = run([{"do": "move", "dx": -8000, "dy": 3}])
    assert driver.events == [("move_rel", -8000, 3)]
    assert clock.now == 0


def test_a_move_spread_over_time_adds_up_to_the_exact_delta():
    """A turn is only as good as its sum: lost counts are a camera that drifts."""
    _, driver, clock = run([{"do": "move", "dx": 13_601, "dy": -77, "ms": 400}])
    moves = [event for event in driver.events if event[0] == "move_rel"]
    assert len(moves) > 10
    assert sum(event[1] for event in moves) == 13_601
    assert sum(event[2] for event in moves) == -77
    assert 0.3 <= clock.now <= 0.401


@pytest.mark.parametrize("ms", [1799, 1601, 400, 9, 7])
def test_a_move_spread_over_time_takes_the_time_it_was_given(ms):
    """`ms // parts` per part lost the remainder: 1799 ms took 1600, and the next step came 199 ms early."""
    _, _, clock = run([{"do": "move", "dx": 500, "dy": 0, "ms": ms}])
    assert clock.now == pytest.approx(ms / 1000, abs=1e-6)


def test_what_sending_the_events_costs_does_not_stretch_a_timed_move():
    """Found live: 200 events at about a millisecond each turned 1799 ms into 1975."""
    driver, clock = Recorder(), Clock()
    send = driver.move_rel

    def slow_send(dx: int, dy: int) -> None:
        clock.now += 0.001
        send(dx, dy)

    driver.move_rel = slow_send
    result, _, _ = run([{"do": "move", "dx": 20_000, "dy": 0, "ms": 1799}], driver, clock=clock)
    assert sum(event[1] for event in driver.events) == 20_000
    assert result["elapsed_ms"] == pytest.approx(1799, abs=60)


def _host_that_oversleeps(clock: Clock, after: float, by: float) -> None:
    """From `after` seconds on, one sleep takes `by` seconds longer than it was asked to."""
    state = {"done": False}

    def oversleep(now: float) -> None:
        if now >= after and not state["done"]:
            state["done"] = True
            clock.now += by

    clock.on_sleep = oversleep


def test_a_key_held_longer_than_planned_is_let_go_and_the_run_stops():
    """The plan said one second. The host slept sixteen; the limit is on what happened, not on what was asked."""
    driver, clock = Recorder(), Clock()
    _host_that_oversleeps(clock, after=0.5, by=MAX_HOLD_MS / 1000 + 3)
    result, _, _ = run([{"do": "key_down", "key": "w"}, {"do": "wait", "ms": 1_000},
                         {"do": "tap", "key": "space"}, {"do": "key_up", "key": "w"}], driver, clock=clock)
    assert result["ok"] is False
    assert result["error"] == "input_overran"
    assert "key:w has been down longer" in result["message"]
    assert driver.events == [("key_down", "w"), ("key_up", "w")]
    assert result["released_at_end"] == {"keys": ["w"], "buttons": []}


def test_a_run_that_outlasts_the_sequence_limit_stops_before_its_next_step():
    driver, clock = Recorder(), Clock()
    _host_that_oversleeps(clock, after=0.1, by=MAX_TOTAL_MS / 1000 + 3)
    result, _, _ = run([{"do": "wait", "ms": 200}, {"do": "tap", "key": "space"}], driver, clock=clock)
    assert result["error"] == "input_overran"
    assert "the sequence has run longer" in result["message"]
    assert driver.events == []


def test_a_hold_at_the_limit_on_a_host_that_is_a_little_late_is_not_refused():
    """The grace is for this: a plan at exactly the limit must survive ordinary lateness."""
    driver, clock = Recorder(), Clock()
    _host_that_oversleeps(clock, after=MAX_HOLD_MS / 1000 - 0.01, by=0.5)
    result, _, _ = run([{"do": "key_down", "key": "w"}, {"do": "wait", "ms": MAX_HOLD_MS},
                         {"do": "key_up", "key": "w"}], driver, clock=clock)
    assert result["ok"] is True
    assert result["steps_done"] == 3
    assert result["elapsed_ms"] >= MAX_HOLD_MS + 400, "the late wake-up never happened, so nothing was tested"


def test_a_key_released_in_time_does_not_count_against_a_later_press():
    driver, clock = Recorder(), Clock()
    steps = [{"do": "key_down", "key": "w"}, {"do": "wait", "ms": 10_000}, {"do": "key_up", "key": "w"},
             {"do": "wait", "ms": 10_000}, {"do": "key_down", "key": "w"}, {"do": "wait", "ms": 10_000},
             {"do": "key_up", "key": "w"}]
    result, _, _ = run(steps, driver, clock=clock)
    assert result["ok"] is True


def test_a_slow_small_move_sends_only_as_many_events_as_it_has_counts():
    _, driver, clock = run([{"do": "move", "dx": 3, "dy": 0, "ms": 400}])
    assert driver.events == [("move_rel", 1, 0)] * 3
    assert clock.now == pytest.approx(0.4, abs=1e-6)


def test_a_button_the_caller_released_is_not_released_again():
    result, driver, _ = run([{"do": "mouse_down", "button": "right"}, {"do": "wait", "ms": 100},
                             {"do": "mouse_up", "button": "right"}])
    assert driver.events == [("button_down", "right"), ("button_up", "right")]
    assert result["released_at_end"] == {"keys": [], "buttons": []}


def test_a_key_released_under_its_other_name_is_released():
    """`esc` and `escape` are one key: sixteen seconds after the release there is nothing to refuse."""
    steps = [{"do": "key_down", "key": "esc"}, {"do": "key_up", "key": "Escape"}, {"do": "wait", "ms": 16_000}]
    result, driver, _ = run(steps)
    assert result["ok"] is True
    assert driver.events == [("key_down", "esc"), ("key_up", "esc")]
    assert result["released_at_end"] == {"keys": [], "buttons": []}


def test_a_press_that_stalls_inside_the_system_call_counts_from_when_it_was_asked_for():
    driver, clock = Recorder(), Clock()
    press = driver.key_down

    def stalled_press(name: str) -> None:
        press(name)
        clock.now += MAX_HOLD_MS / 1000 + 3

    driver.key_down = stalled_press
    result, _, _ = run([{"do": "key_down", "key": "w"}, {"do": "tap", "key": "space"}], driver, clock=clock)
    assert result["error"] == "input_overran"
    assert driver.events == [("key_down", "w"), ("key_up", "w")]


def test_a_timed_move_that_is_already_late_still_looks_before_each_part():
    """Every deadline had passed, so nothing slept, so nothing was checked: the rest went to the wrong window."""
    driver, clock = Recorder(), Clock()
    send = driver.move_rel

    def lose_focus_while_sending(dx: int, dy: int) -> None:
        send(dx, dy)
        driver.title = "Terminal"
        clock.now += 1.0

    driver.move_rel = lose_focus_while_sending
    result, _, _ = run([{"do": "move", "dx": 400, "dy": 0, "ms": 32}], driver, clock=clock)
    assert len(driver.events) == 1
    assert result["error"] == "input_guard_failed"
    assert result["active_title"] == "Terminal"


def test_absolute_moves_and_the_wheel_reach_the_driver():
    _, driver, _ = run([{"do": "move_to", "x": 1208, "y": 976}, {"do": "scroll", "clicks": -2}])
    assert driver.events == [("move_to", 1208, 976), ("scroll", -2)]
