"""#621: the request for a desktop wait, and the loop that repeats a look until it is true or time is up."""
# No desktop here: the look is a function the test writes, the clock is virtual.
from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from arena.desktop import wait
from arena.desktop.wait import (
    DEFAULT_POLL_MS,
    DEFAULT_TIMEOUT_MS,
    LOOK_GRACE_MS,
    MAX_POLL_MS,
    MAX_TIMEOUT_MS,
    MIN_POLL_MS,
    REGION_BOUNDS,
    CannotLook,
    Look,
    WaitError,
    WaitPlan,
    plan_wait,
    wait_for,
)
from arena.handler_errors import BadRequest, BodyFieldError


class Clock:
    """Virtual time: sleeping advances it, and a look may cost time too."""

    def __init__(self) -> None:
        """Start at a moment that is not zero, so nothing passes by reading the clock raw."""
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _run(plan: WaitPlan, answers, clock: Clock | None = None, look_costs: float = 0.0):
    """Wait with looks that give `answers` in turn (the last one repeats); returns the result and the clock."""
    clock = clock or Clock()
    given = list(answers)

    async def look() -> Look:
        clock.now += look_costs
        return given.pop(0) if len(given) > 1 else given[0]

    return asyncio.run(wait_for(plan, look, clock=clock.time, sleep=clock.sleep)), clock


def _plan(**fields) -> WaitPlan:
    return plan_wait({"for": "window", "title": "game", **fields})


def test_a_request_is_planned_with_its_defaults():
    plan = plan_wait({"for": "window", "title": "  Game  "})
    assert plan == WaitPlan("window", DEFAULT_TIMEOUT_MS, DEFAULT_POLL_MS,
                            {"title": "Game", "class": "", "state": "present"})
    assert (DEFAULT_TIMEOUT_MS, DEFAULT_POLL_MS) == (10_000, 500)
    assert (MAX_TIMEOUT_MS, MIN_POLL_MS, MAX_POLL_MS) == (45_000, 100, 5_000)


@pytest.mark.parametrize(("body", "want"), [
    ({"for": "window", "class": "Chrome", "state": "active"}, {"title": "", "class": "Chrome", "state": "active"}),
    ({"for": "window", "title": "x", "state": "absent"}, {"title": "x", "class": "", "state": "absent"}),
    ({"for": "screen"}, {"until": "change", "region": None}),
    ({"for": "screen", "timeout_ms": 1}, {"until": "change", "region": None}),
    ({"for": "screen", "until": "stable"}, {"until": "stable", "region": None, "stable_ms": 1000}),
    ({"for": "screen", "until": "stable", "timeout_ms": 100}, {"until": "stable", "region": None, "stable_ms": 100}),
    ({"for": "screen", "until": "stable", "stable_ms": 250, "region": {"x": -5, "y": 0, "width": 1, "height": 2}},
     {"until": "stable", "stable_ms": 250, "region": {"x": -5, "y": 0, "width": 1, "height": 2}}),
    ({"for": "screen", "until": "stable", "stable_ms": 45000, "timeout_ms": 45000},
     {"until": "stable", "stable_ms": 45000, "region": None}),
    ({"for": "screen", "until": "stable", "timeout_ms": 400}, {"until": "stable", "stable_ms": 400, "region": None}),
    ({"for": "screen", "until": "stable", "timeout_ms": 400, "stable_ms": 400},
     {"until": "stable", "stable_ms": 400, "region": None}),
    ({"for": "text", "text": " Loading "},
     {"text": "Loading", "state": "present", "region": None, "min_confidence": 40}),
    ({"for": "text", "text": "x", "state": "absent", "min_confidence": 0},
     {"text": "x", "state": "absent", "region": None, "min_confidence": 0}),
    ({"for": "text", "text": "x", "region": {"x": 0, "y": 0, "width": 2, "height": 1}},
     {"text": "x", "state": "present", "region": {"x": 0, "y": 0, "width": 2, "height": 1}, "min_confidence": 40}),
    ({"for": "text", "text": "x", "min_confidence": 100},
     {"text": "x", "state": "present", "region": None, "min_confidence": 100}),
])
def test_each_kind_of_wait_takes_its_own_fields(body, want):
    assert plan_wait(body).want == want


@pytest.mark.parametrize(("fields", "expected"), [
    ({"timeout_ms": 1}, (1, DEFAULT_POLL_MS)),
    ({"timeout_ms": MAX_TIMEOUT_MS}, (MAX_TIMEOUT_MS, DEFAULT_POLL_MS)),
    ({"poll_ms": MIN_POLL_MS}, (DEFAULT_TIMEOUT_MS, MIN_POLL_MS)),
    ({"poll_ms": MAX_POLL_MS}, (DEFAULT_TIMEOUT_MS, MAX_POLL_MS)),
])
def test_the_limits_themselves_are_allowed(fields, expected):
    plan = _plan(**fields)
    assert (plan.timeout_ms, plan.poll_ms) == expected


@pytest.mark.parametrize(("body", "says"), [
    ({}, "'for' must be one of: window, screen, text"),
    ({"for": "mouse"}, "'for' must be one of: window, screen, text"),
    ({"for": ["window"]}, "'for' must be one of: window, screen, text"),
    ({"for": "window"}, "a window wait needs 'title' or 'class': words from the title or from the window class"),
    ({"for": "window", "title": " -- ", "class": "!"}, "a window wait needs 'title' or 'class'"),
    ({"for": "window", "title": 7}, "'title' must be a string"),
    ({"for": "window", "title": "x", "class": None}, "'class' must be a string"),
    ({"for": "window", "title": "x", "state": "gone"}, "'state' must be one of: present, absent, active"),
    ({"for": "window", "title": "x", "timeout": 5},
     "unknown field(s) for a window wait: timeout; it takes: for, timeout_ms, poll_ms, title, class, state"),
    ({"for": "window", "title": "x", "text": "y", "region": None},
     "unknown field(s) for a window wait: region, text; it takes"),
    ({"for": "screen", "title": "x"},
     "unknown field(s) for a screen wait: title; it takes: for, timeout_ms, poll_ms, until, stable_ms, region"),
    ({"for": "screen", "until": "quiet"}, "'until' must be one of: change, stable"),
    ({"for": "screen", "stable_ms": 500}, "'stable_ms' belongs to until: stable"),
    ({"for": "screen", "until": "stable", "stable_ms": 501, "timeout_ms": 500},
     "'stable_ms' is longer than 'timeout_ms': the screen could never be still for that long"),
    ({"for": "screen", "until": "stable", "timeout_ms": 99}, "'stable_ms' is longer than 'timeout_ms'"),
    ({"for": "screen", "region": [1, 2, 3, 4]}, "'region' must be an object with exactly x, y, width and height"),
    ({"for": "screen", "region": {"x": 1, "y": 2, "width": 3}}, "'region' must be an object with exactly"),
    ({"for": "screen", "region": {"x": 1, "y": 2, "width": 3, "height": 4, "z": 5}}, "'region' must be an object"),
    ({"for": "text"}, "a text wait needs 'text': the words to look for on the screen"),
    ({"for": "text", "text": "   "}, "a text wait needs 'text'"),
    ({"for": "text", "text": "x", "state": "active"}, "'state' must be one of: present, absent"),
    ({"for": "text", "text": "x", "until": "stable"}, "unknown field(s) for a text wait: until; it takes"),
])
def test_a_request_that_cannot_be_planned_says_why(body, says):
    with pytest.raises(WaitError) as refused:
        plan_wait(body)
    assert str(refused.value).startswith(says)


WINDOW = {"for": "window", "title": "x"}
STILL = {"for": "screen", "until": "stable"}
WORDS = {"for": "text", "text": "x"}
BOX = {"x": 1, "y": 2, "width": 3, "height": 4}


@pytest.mark.parametrize(("body", "field", "says", "received"), [
    (WINDOW | {"timeout_ms": 0}, "timeout_ms", "an integer no smaller than 1", "number"),
    (WINDOW | {"timeout_ms": 45001}, "timeout_ms", "an integer no greater than 45000", "number"),
    (WINDOW | {"timeout_ms": True}, "timeout_ms", "an integer", "boolean"),
    (WINDOW | {"timeout_ms": 1.5}, "timeout_ms", "an integer", "number"),
    (WINDOW | {"timeout_ms": [9]}, "timeout_ms", "an integer", "array"),
    (WINDOW | {"timeout_ms": "soon"}, "timeout_ms", "an integer", "string"),
    (WINDOW | {"poll_ms": 99}, "poll_ms", "an integer no smaller than 100", "number"),
    (WINDOW | {"poll_ms": 5001}, "poll_ms", "an integer no greater than 5000", "number"),
    (STILL | {"stable_ms": 99}, "stable_ms", "an integer no smaller than 100", "number"),
    (STILL | {"stable_ms": 45001}, "stable_ms", "an integer no greater than 45000", "number"),
    (WORDS | {"min_confidence": -1}, "min_confidence", "an integer no smaller than 0", "number"),
    (WORDS | {"min_confidence": 101}, "min_confidence", "an integer no greater than 100", "number"),
    ({"for": "screen", "region": BOX | {"x": 1.5}}, "region.x", "an integer", "number"),
    ({"for": "screen", "region": BOX | {"y": None}}, "region.y", "an integer", "null"),
    ({"for": "screen", "region": BOX | {"width": True}}, "region.width", "an integer", "boolean"),
    ({"for": "text", "text": "x", "region": BOX | {"height": ""}}, "region.height", "an integer", "string"),
    ({"for": "screen", "region": BOX | {"width": 0}}, "region.width", "an integer no smaller than 1", "number"),
    ({"for": "screen", "region": BOX | {"height": 0}}, "region.height", "an integer no smaller than 1", "number"),
    ({"for": "screen", "region": BOX | {"width": 1000001}}, "region.width", "an integer no greater than 1000000",
     "number"),
    ({"for": "screen", "region": BOX | {"x": -1000001}}, "region.x", "an integer no smaller than -1000000", "number"),
    ({"for": "screen", "region": BOX | {"y": 10 ** 30}}, "region.y", "an integer no greater than 1000000", "number"),
])
def test_a_number_that_cannot_be_used_is_refused_by_name(body, field, says, received):
    with pytest.raises(BodyFieldError) as refused:
        plan_wait(body)
    assert str(refused.value) == f"body field {field!r} must be {says}, received {received}"
    assert refused.value.details == {"field": field, "received": received}


@pytest.mark.parametrize(("body", "expected"), [
    (WINDOW | {"timeout_ms": "9", "poll_ms": 250.0}, (9, 250)),
    (WINDOW | {"timeout_ms": None, "poll_ms": ""}, (10000, 500)),
])
def test_numbers_are_read_the_way_every_body_number_is(body, expected):
    plan = plan_wait(body)
    assert (plan.timeout_ms, plan.poll_ms) == expected


def test_the_numbers_of_each_kind_are_read_the_same_way():
    assert plan_wait(STILL | {"stable_ms": "700"}).want["stable_ms"] == 700
    assert plan_wait(STILL | {"stable_ms": None, "timeout_ms": 400}).want["stable_ms"] == 400
    assert plan_wait(WORDS | {"min_confidence": 55.0}).want["min_confidence"] == 55
    assert plan_wait(WORDS | {"min_confidence": None}).want["min_confidence"] == 40
    assert plan_wait({"for": "screen", "region": BOX | {"x": "10", "width": 3.0}}).want["region"] == BOX | {"x": 10}


def test_the_limits_of_a_region_are_these():
    assert REGION_BOUNDS == {"x": (-1000000, 1000000), "y": (-1000000, 1000000),
                             "width": (1, 1000000), "height": (1, 1000000)}
    assert list(REGION_BOUNDS) == ["x", "y", "width", "height"]


def test_a_region_may_start_left_of_or_above_the_main_display_and_be_one_pixel():
    far = {"x": -1000000, "y": 1000000, "width": 1, "height": 1000000}
    assert plan_wait({"for": "screen", "region": far}).want["region"] == far
    assert list(plan_wait({"for": "screen", "region": dict(reversed(far.items()))}).want["region"]) == list(BOX)


def test_a_refusal_is_one_the_route_decorators_answer_with_a_400():
    assert issubclass(WaitError, BadRequest)
    assert issubclass(BodyFieldError, BadRequest)


def test_what_is_already_true_is_answered_at_the_first_look():
    result, clock = _run(_plan(), [Look(True, {"matches": 1})])
    assert result == {"ok": True, "happened": True, "for": "window", "waited_ms": 0, "polls": 1, "matches": 1}
    assert clock.sleeps == []


def test_the_loop_looks_again_after_each_pause_until_it_is_true():
    result, clock = _run(_plan(poll_ms=200), [Look(False), Look(False, {"matches": 0}), Look(True, {"matches": 2})])
    assert result == {"ok": True, "happened": True, "for": "window", "waited_ms": 400, "polls": 3, "matches": 2}
    assert clock.sleeps == [0.2, 0.2]


def test_running_out_of_time_is_an_answer_with_what_was_last_seen():
    result, clock = _run(_plan(timeout_ms=1000, poll_ms=400), [Look(False, {"matches": 0})])
    assert result == {"ok": True, "happened": False, "for": "window", "waited_ms": 1000, "polls": 4, "matches": 0}
    # The last pause is cut short so that the last look is at the deadline, not 200 ms after it.
    assert clock.sleeps == pytest.approx([0.4, 0.4, 0.2])


def test_the_state_reached_exactly_at_the_deadline_counts():
    result, _ = _run(_plan(timeout_ms=300, poll_ms=300), [Look(False), Look(True)])
    assert (result["happened"], result["waited_ms"], result["polls"]) == (True, 300, 2)


def test_a_millisecond_left_is_still_time_to_look_again():
    result, _ = _run(_plan(timeout_ms=301, poll_ms=300), [Look(False), Look(False), Look(True)])
    assert (result["happened"], result["waited_ms"], result["polls"]) == (True, 301, 3)


def test_a_plan_and_a_look_cannot_be_changed_after_they_are_made():
    with pytest.raises(FrozenInstanceError):
        _plan().timeout_ms = 1
    with pytest.raises(FrozenInstanceError):
        Look(False).done = True


def test_time_spent_looking_is_time_waited():
    """A look that takes 250 ms (OCR does) uses up the timeout too: four looks, not ten."""
    result, clock = _run(_plan(timeout_ms=1000, poll_ms=100), [Look(False)], look_costs=0.25)
    assert (result["happened"], result["polls"]) == (False, 4)
    assert result["waited_ms"] == 1250
    assert clock.sleeps == pytest.approx([0.1, 0.1, 0.05])


def test_a_look_that_overruns_the_deadline_is_the_last_one():
    result, clock = _run(_plan(timeout_ms=200, poll_ms=100), [Look(False)], look_costs=0.5)
    assert (result["happened"], result["polls"], result["waited_ms"]) == (False, 1, 500)
    assert clock.sleeps == []


def test_a_look_that_cannot_be_made_is_not_a_timeout():
    async def look() -> Look:
        raise CannotLook({"ok": False, "error": "no display", "unavailable": ["grim"]})

    plan = _plan()
    with pytest.raises(CannotLook) as failed:
        asyncio.run(wait_for(plan, look))
    assert failed.value.result == {"ok": False, "error": "no display", "unavailable": ["grim"]}
    assert str(failed.value) == "no display"
    assert str(CannotLook({"ok": False})) == "the desktop could not be looked at"


def test_the_real_clock_and_sleep_are_the_defaults():
    looks = iter([Look(False), Look(True, {"matches": 1})])

    async def look() -> Look:
        return next(looks)

    result = asyncio.run(wait_for(_plan(timeout_ms=2000, poll_ms=100), look))
    assert (result["happened"], result["polls"]) == (True, 2)
    assert 90 <= result["waited_ms"] < 1500


def test_each_look_is_given_the_time_left_and_a_fixed_grace_after_it(monkeypatch):
    """The answer comes within `timeout_ms + LOOK_GRACE_MS`, however long a producer would take."""
    limits: list[float] = []

    async def within(running, seconds):
        limits.append(seconds)
        return await running

    monkeypatch.setattr(wait, "_within", within)
    result, _ = _run(_plan(timeout_ms=1000, poll_ms=400), [Look(False)], look_costs=0.1)
    assert result["polls"] == 3
    # Read before each look: 0, 500 and 1000 ms into a wait of 1000 ms.
    assert limits == pytest.approx([11.0, 10.5, 10.0])
    assert LOOK_GRACE_MS == 10_000
    assert MAX_TIMEOUT_MS + LOOK_GRACE_MS < 60_000


def test_a_look_still_running_when_the_grace_is_over_is_abandoned_and_is_not_a_timeout(monkeypatch):
    stopped: list[str] = []

    async def look() -> Look:
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append("cancelled")
        return Look(True)

    monkeypatch.setattr(wait, "LOOK_GRACE_MS", 30)
    plan = _plan(timeout_ms=1)
    with pytest.raises(CannotLook) as failed:
        asyncio.run(wait_for(plan, look))
    assert failed.value.result == {"ok": False, "error": (
        "a look at the desktop was still running 30 ms after the time to wait was up, and was abandoned")}
    assert failed.value.__suppress_context__ is True
    assert stopped == ["cancelled"]


def test_a_look_that_ends_inside_the_grace_is_answered_as_it_was_seen(monkeypatch):
    async def look() -> Look:
        await asyncio.sleep(0.05)
        return Look(True, {"matches": 1})

    monkeypatch.setattr(wait, "LOOK_GRACE_MS", 5000)
    result = asyncio.run(wait_for(_plan(timeout_ms=1), look))
    assert (result["happened"], result["polls"], result["matches"]) == (True, 1, 1)
    assert result["waited_ms"] >= 50
