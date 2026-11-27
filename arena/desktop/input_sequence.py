"""Timed input sequences: what a caller may ask for, and the runner (#616).

`desktop.key` and `desktop.click` press and release in one call, and every
call is a round trip. That leaves three things out of reach: holding a key or
a button, moving the pointer by a delta, and timing two actions against each
other ("hold jump, 280 ms later right-click"). A sequence is a list of steps
the bridge runs on the host in one call.

This module is the part that does not depend on a platform: it validates the
steps before anything is pressed, and it runs them against a driver. Two
properties are deliberate:

* Nothing stays held. Whatever a sequence pressed is released when it ends,
  however it ends -- finished, refused by the window guard, stopped by the
  control lease, or broken by an exception. If the system refuses a release,
  the result says which key or button is still down instead of reporting success.
* The window is named. A sequence is refused unless the caller says which
  foreground window it is meant for, and it stops the moment that window is
  no longer in front. Held keys in the wrong window are how an agent types
  into a terminal it never meant to touch.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

MAX_STEPS = 200
#: The longest one key or button may stay down.
MAX_HOLD_MS = 15_000
#: The longest a whole sequence may run.
MAX_TOTAL_MS = 60_000
#: A wait is slept in slices so a stop request is noticed inside it.
_SLICE_MS = 50
_DEFAULT_PRESS_MS = 60
_BUTTONS = ("left", "right", "middle")
_MAX_DELTA = 100_000
_MAX_CLICKS = 100

__all__ = [
    "MAX_HOLD_MS", "MAX_STEPS", "MAX_TOTAL_MS",
    "InputDriver", "SequenceError", "plan_sequence", "planned_duration_ms", "run_sequence",
]


class SequenceError(ValueError):
    """A step the bridge will not run; `index` is the step's position."""

    def __init__(self, message: str, index: int | None = None) -> None:
        super().__init__(message)
        self.index = index


class InputDriver(Protocol):
    """What a platform has to provide for a sequence to run on it."""

    def knows_key(self, name: str) -> bool: ...
    def key_down(self, name: str) -> None: ...
    def key_up(self, name: str) -> None: ...
    def button_down(self, name: str) -> None: ...
    def button_up(self, name: str) -> None: ...
    def move_rel(self, dx: int, dy: int) -> None: ...
    def move_to(self, x: int, y: int) -> None: ...
    def scroll(self, clicks: int) -> None: ...
    def foreground_title(self) -> str: ...


def _integer(step: dict[str, Any], field: str, index: int, *, low: int, high: int, default: int | None = None) -> int:
    value = step.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SequenceError(f"step {index}: '{field}' must be an integer", index)
    if not low <= value <= high:
        raise SequenceError(f"step {index}: '{field}' must be between {low} and {high}", index)
    return value


def _key_name(step: dict[str, Any], index: int, driver: InputDriver) -> str:
    name = step.get("key")
    if not isinstance(name, str) or not name.strip():
        raise SequenceError(f"step {index}: 'key' must be a key name", index)
    name = name.strip().lower()
    if not driver.knows_key(name):
        raise SequenceError(f"step {index}: unknown key {name!r}", index)
    return name


def _button_name(step: dict[str, Any], index: int) -> str:
    name = step.get("button", "left")
    if name not in _BUTTONS:
        raise SequenceError(f"step {index}: 'button' must be one of {', '.join(_BUTTONS)}", index)
    return name


def _press_ms(step: dict[str, Any], index: int) -> int:
    return _integer(step, "ms", index, low=1, high=MAX_HOLD_MS, default=_DEFAULT_PRESS_MS)


def _plan_wait(step, index, _driver):
    return {"do": "wait", "ms": _integer(step, "ms", index, low=0, high=MAX_TOTAL_MS)}


def _plan_key(step, index, driver):
    return {"do": step["do"], "key": _key_name(step, index, driver)}


def _plan_tap(step, index, driver):
    return {"do": "tap", "key": _key_name(step, index, driver), "ms": _press_ms(step, index)}


def _plan_button(step, index, _driver):
    return {"do": step["do"], "button": _button_name(step, index)}


def _plan_click(step, index, _driver):
    return {"do": "click", "button": _button_name(step, index), "ms": _press_ms(step, index)}


def _plan_move(step, index, _driver):
    return {
        "do": "move",
        "dx": _integer(step, "dx", index, low=-_MAX_DELTA, high=_MAX_DELTA, default=0),
        "dy": _integer(step, "dy", index, low=-_MAX_DELTA, high=_MAX_DELTA, default=0),
        "ms": _integer(step, "ms", index, low=0, high=MAX_HOLD_MS, default=0),
    }


def _plan_move_to(step, index, _driver):
    return {
        "do": "move_to",
        "x": _integer(step, "x", index, low=-_MAX_DELTA, high=_MAX_DELTA),
        "y": _integer(step, "y", index, low=-_MAX_DELTA, high=_MAX_DELTA),
    }


def _plan_scroll(step, index, _driver):
    return {"do": "scroll", "clicks": _integer(step, "clicks", index, low=-_MAX_CLICKS, high=_MAX_CLICKS)}


_PLANNERS: dict[str, Callable[[dict[str, Any], int, InputDriver], dict[str, Any]]] = {
    "wait": _plan_wait,
    "key_down": _plan_key,
    "key_up": _plan_key,
    "tap": _plan_tap,
    "mouse_down": _plan_button,
    "mouse_up": _plan_button,
    "click": _plan_click,
    "move": _plan_move,
    "move_to": _plan_move_to,
    "scroll": _plan_scroll,
}


def _step_ms(step: dict[str, Any]) -> int:
    return int(step.get("ms", 0))


def planned_duration_ms(steps: list[dict[str, Any]]) -> int:
    """How long the steps take if nothing stops them."""
    return sum(_step_ms(step) for step in steps)


def _held_name(step: dict[str, Any]) -> str:
    return "key:" + step["key"] if "key" in step else "button:" + step["button"]


def _check_holds(steps: list[dict[str, Any]]) -> None:
    """Refuse a plan that keeps one key or button down past MAX_HOLD_MS."""
    down_since: dict[str, int] = {}
    now = 0
    for index, step in enumerate(steps):
        if step["do"] in ("key_down", "mouse_down"):
            down_since.setdefault(_held_name(step), now)
        elif step["do"] in ("key_up", "mouse_up"):
            down_since.pop(_held_name(step), None)
        now += _step_ms(step)
        for name, since in down_since.items():
            if now - since > MAX_HOLD_MS:
                raise SequenceError(
                    f"step {index}: {name} would stay down longer than {MAX_HOLD_MS} ms", index)


def plan_sequence(raw_steps: Any, driver: InputDriver) -> list[dict[str, Any]]:
    """Validate the caller's steps; raises SequenceError before anything is pressed."""
    if not isinstance(raw_steps, list) or not raw_steps:
        raise SequenceError("'steps' must be a non-empty list")
    if len(raw_steps) > MAX_STEPS:
        raise SequenceError(f"'steps' may hold at most {MAX_STEPS} steps")
    steps = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise SequenceError(f"step {index}: must be an object", index)
        planner = _PLANNERS.get(str(raw.get("do")))
        if planner is None:
            raise SequenceError(f"step {index}: 'do' must be one of {', '.join(_PLANNERS)}", index)
        steps.append(planner(raw, index, driver))
    total = planned_duration_ms(steps)
    if total > MAX_TOTAL_MS:
        raise SequenceError(f"the sequence would run {total} ms; the limit is {MAX_TOTAL_MS} ms")
    _check_holds(steps)
    return steps


class _Stopped(Exception):
    """Raised inside the runner to unwind to the release-everything block."""

    def __init__(self, reason: dict[str, Any]) -> None:
        super().__init__(reason.get("error", "stopped"))
        self.reason = reason


class _Run:
    """One execution: remembers what is down so it can always be let go."""

    def __init__(self, driver: InputDriver, required_title: str, should_stop, sleep, clock) -> None:
        self.driver = driver
        self.required_title = required_title.lower()
        self.should_stop = should_stop
        self.sleep = sleep
        self.clock = clock
        self.keys: list[str] = []
        self.buttons: list[str] = []

    def check(self) -> None:
        """Stop if the control lease refuses or another window came to the front."""
        blocked = self.should_stop() if self.should_stop else None
        if blocked:
            raise _Stopped({key: value for key, value in dict(blocked).items() if key != "ok"})
        title = self.driver.foreground_title()
        if self.required_title not in title.lower():
            raise _Stopped({
                "error": "input_guard_failed",
                "message": "Active window does not match required title",
                "active_title": title,
            })

    def wait(self, ms: int) -> None:
        deadline = self.clock() + ms / 1000.0
        while True:
            left = deadline - self.clock()
            if left <= 0:
                return
            self.sleep(min(left, _SLICE_MS / 1000.0))
            self.check()

    def key_down(self, name: str) -> None:
        self.driver.key_down(name)
        if name not in self.keys:
            self.keys.append(name)

    def key_up(self, name: str) -> None:
        self.driver.key_up(name)
        if name in self.keys:
            self.keys.remove(name)

    def button_down(self, name: str) -> None:
        self.driver.button_down(name)
        if name not in self.buttons:
            self.buttons.append(name)

    def button_up(self, name: str) -> None:
        self.driver.button_up(name)
        if name in self.buttons:
            self.buttons.remove(name)

    def move(self, dx: int, dy: int, ms: int) -> None:
        """Send the delta at once, or spread over `ms` so the counts add up exactly."""
        parts = max(1, min(200, ms // 8))
        sent_x = sent_y = 0
        for part in range(1, parts + 1):
            want_x, want_y = round(dx * part / parts), round(dy * part / parts)
            if (want_x, want_y) != (sent_x, sent_y):
                self.driver.move_rel(want_x - sent_x, want_y - sent_y)
                sent_x, sent_y = want_x, want_y
            if ms:
                self.wait(ms // parts)

    def release_all(self) -> tuple[dict[str, list[str]], list[str]]:
        """Let go of everything still down; returns what was released and what refused to be."""
        released: dict[str, list[str]] = {"keys": [], "buttons": []}
        stuck: list[str] = []
        pending = [("buttons", "button:", self.driver.button_up, name) for name in reversed(self.buttons)]
        pending += [("keys", "key:", self.driver.key_up, name) for name in reversed(self.keys)]
        for kind, prefix, release, name in pending:
            if _released(release, name):
                released[kind].append(name)
            else:
                stuck.append(prefix + name)
        self.keys.clear()
        self.buttons.clear()
        return released, stuck


def _released(action: Callable[[str], None], name: str) -> bool:
    """Try one release; a failure must not stop the releases after it."""
    try:
        action(name)
    except Exception:  # noqa: BLE001 -- the next input still has to be let go
        return False
    return True


def _do_tap(run: _Run, step: dict[str, Any]) -> None:
    run.key_down(step["key"])
    run.wait(step["ms"])
    run.key_up(step["key"])


def _do_click(run: _Run, step: dict[str, Any]) -> None:
    run.button_down(step["button"])
    run.wait(step["ms"])
    run.button_up(step["button"])


_ACTIONS: dict[str, Callable[[_Run, dict[str, Any]], None]] = {
    "wait": lambda run, step: run.wait(step["ms"]),
    "key_down": lambda run, step: run.key_down(step["key"]),
    "key_up": lambda run, step: run.key_up(step["key"]),
    "tap": _do_tap,
    "mouse_down": lambda run, step: run.button_down(step["button"]),
    "mouse_up": lambda run, step: run.button_up(step["button"]),
    "click": _do_click,
    "move": lambda run, step: run.move(step["dx"], step["dy"], step["ms"]),
    "move_to": lambda run, step: run.driver.move_to(step["x"], step["y"]),
    "scroll": lambda run, step: run.driver.scroll(step["clicks"]),
}


def run_sequence(
    steps: list[dict[str, Any]],
    driver: InputDriver,
    *,
    required_title: str,
    should_stop: Callable[[], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run planned steps; whatever happens, nothing is left held down."""
    run = _Run(driver, required_title, should_stop, sleep, clock)
    started = clock()
    done = 0
    result: dict[str, Any] = {"ok": True}
    try:
        for step in steps:
            run.check()
            _ACTIONS[step["do"]](run, step)
            done += 1
    except _Stopped as stop:
        result = {"ok": False, **stop.reason}
    except OSError as exc:
        result = {"ok": False, "error": "input_failed", "message": str(exc)}
    finally:
        released, stuck = run.release_all()
    if stuck:
        # Say so: a key the system would not release is still down for the user.
        result = {**result, "ok": False, "release_failed": stuck}
        result.setdefault("error", "input_failed")
        result.setdefault("message", "could not release: " + ", ".join(stuck))
    result.update({
        "steps_done": done,
        "steps_total": len(steps),
        "elapsed_ms": round((clock() - started) * 1000),
        "released_at_end": released,
    })
    return result
