"""Waiting, on the host, for the desktop to reach a state (#621)."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from arena.desktop.text_matching import normalize_text
from arena.handler_errors import BadRequest, BodyFieldError
from arena.handler_params import body_int

# An agent that needed "the launcher window is up" or "the loading bar has
# stopped moving" had one way to learn it: sleep, take a screenshot, look,
# repeat -- a round trip and a step per look. A look is cheap on the host, so
# the loop lives here and the agent asks once.
#
# This module is the request and the loop. What a look *is* -- listing
# windows, comparing two captures, reading the screen -- is in `wait_looks`.

#: Under the 60 s the MCP tools wait for the bridge, with room for a last look (`LOOK_GRACE_MS`).
MAX_TIMEOUT_MS = 45_000
DEFAULT_TIMEOUT_MS = 10_000
MIN_POLL_MS = 100
MAX_POLL_MS = 5_000
DEFAULT_POLL_MS = 500
DEFAULT_STABLE_MS = 1_000
#: How long after the time is up a look that is still running is waited for. A look is a producer's own
#: work -- a listing, a capture, a reading -- and one that hangs must not hold the request past what the
#: caller's own HTTP timeout allows: the answer comes within `timeout_ms + LOOK_GRACE_MS`.
LOOK_GRACE_MS = 10_000

_COMMON = ("for", "timeout_ms", "poll_ms")
#: Further than any desktop reaches, and well inside what the capture calls take as a C int.
REGION_FAR = 1_000_000
#: The least and the most each side of a region may be. A display left of or above the main one has
#: negative corners; a region has at least one pixel.
REGION_BOUNDS: dict[str, tuple[int, int]] = {
    "x": (-REGION_FAR, REGION_FAR), "y": (-REGION_FAR, REGION_FAR),
    "width": (1, REGION_FAR), "height": (1, REGION_FAR),
}
#: What each kind of wait may be told, besides the common fields.
FIELDS: dict[str, tuple[str, ...]] = {
    "window": ("title", "class", "state"),
    "screen": ("until", "stable_ms", "region"),
    "text": ("text", "state", "region", "min_confidence"),
}
_CHOICES: dict[tuple[str, str], tuple[str, ...]] = {
    ("window", "state"): ("present", "absent", "active"),
    ("screen", "until"): ("change", "stable"),
    ("text", "state"): ("present", "absent"),
}


class WaitError(BadRequest):
    """The request cannot be planned: the caller's mistake, which the route decorator answers with a 400."""


class CannotLook(Exception):
    """A look failed; carries the producer's own result (`ok: false`, perhaps `unavailable`)."""

    def __init__(self, result: Mapping[str, Any]) -> None:
        """Keep the result as it was handed over."""
        super().__init__(str(result.get("error") or "the desktop could not be looked at"))
        self.result = dict(result)


@dataclass(frozen=True)
class WaitPlan:
    """A checked request: what to wait for, for how long, how often to look."""

    kind: str
    timeout_ms: int
    poll_ms: int
    want: dict[str, Any]


@dataclass(frozen=True)
class Look:
    """One look: whether the state is there, and what was seen."""

    done: bool
    seen: dict[str, Any] = field(default_factory=dict)


class Looker(Protocol):
    """One look at the desktop, repeated by `wait_for`; raises `CannotLook` when it could not be made."""

    def __call__(self) -> Awaitable[Look]:
        """Look once."""


def _edge(region: Mapping[str, Any], name: str) -> int:
    """One side of the region, read the way every number in a body is; it cannot be left out."""
    label = f"region.{name}"
    number = body_int({label: region[name]}, label, default=None, bounds=REGION_BOUNDS[name])
    if number is None:
        raise BodyFieldError(label, region[name])
    return number


def _words(body: Mapping[str, Any], name: str) -> str:
    """A text field, trimmed; absent is empty."""
    value = body.get(name, "")
    if not isinstance(value, str):
        raise WaitError(f"'{name}' must be a string")
    return value.strip()


def _choice(body: Mapping[str, Any], kind: str, name: str) -> str:
    """One of the values the field allows; the first is the default."""
    allowed = _CHOICES[(kind, name)]
    value = body.get(name, allowed[0])
    if value not in allowed:
        raise WaitError(f"'{name}' must be one of: {', '.join(allowed)}")
    return str(value)


def _region(body: Mapping[str, Any]) -> dict[str, int] | None:
    """The rectangle to look at, or None for the whole desktop."""
    region = body.get("region")
    if region is None:
        return None
    if not isinstance(region, Mapping) or sorted(region) != sorted(REGION_BOUNDS):
        raise WaitError("'region' must be an object with exactly x, y, width and height")
    return {name: _edge(region, name) for name in REGION_BOUNDS}


def _window(body: Mapping[str, Any], _timeout_ms: int) -> dict[str, Any]:
    want = {"title": _words(body, "title"), "class": _words(body, "class"), "state": _choice(body, "window", "state")}
    # Compared as folded words, the way the window routes compare them: a
    # title of punctuation alone folds to nothing and would match every window.
    if not normalize_text(want["title"]) and not normalize_text(want["class"]):
        raise WaitError("a window wait needs 'title' or 'class': words from the title or from the window class")
    return want


def _screen(body: Mapping[str, Any], timeout_ms: int) -> dict[str, Any]:
    want: dict[str, Any] = {"until": _choice(body, "screen", "until"), "region": _region(body)}
    if want["until"] == "change":
        if "stable_ms" in body:
            raise WaitError("'stable_ms' belongs to until: stable")
        return want
    # Left out, it is a second -- or the whole timeout when that is shorter.
    usual = max(MIN_POLL_MS, min(DEFAULT_STABLE_MS, timeout_ms))
    stable_ms = body_int(body, "stable_ms", default=usual, bounds=(MIN_POLL_MS, MAX_TIMEOUT_MS))
    if stable_ms > timeout_ms:
        raise WaitError("'stable_ms' is longer than 'timeout_ms': the screen could never be still for that long")
    want["stable_ms"] = stable_ms
    return want


def _text(body: Mapping[str, Any], _timeout_ms: int) -> dict[str, Any]:
    text = _words(body, "text")
    if not text:
        raise WaitError("a text wait needs 'text': the words to look for on the screen")
    return {"text": text, "state": _choice(body, "text", "state"), "region": _region(body),
            "min_confidence": body_int(body, "min_confidence", default=40, bounds=(0, 100))}


_WANTS: dict[str, Callable[[Mapping[str, Any], int], dict[str, Any]]] = {
    "window": _window, "screen": _screen, "text": _text}


def plan_wait(body: Mapping[str, Any]) -> WaitPlan:
    """Check a request body and turn it into a plan, or say what is wrong with it."""
    kind = body.get("for")
    if not isinstance(kind, str) or kind not in FIELDS:
        raise WaitError(f"'for' must be one of: {', '.join(FIELDS)}")
    known = _COMMON + FIELDS[kind]
    unknown = sorted(str(name) for name in body if name not in known)
    if unknown:
        raise WaitError(f"unknown field(s) for a {kind} wait: {', '.join(unknown)}; it takes: {', '.join(known)}")
    # Numbers go through `body_int`, like every number in a request body (#270): a refusal names the field
    # and the JSON type that arrived, "10" and 10.0 are 10, and null is "not given".
    timeout_ms = body_int(body, "timeout_ms", default=DEFAULT_TIMEOUT_MS, bounds=(1, MAX_TIMEOUT_MS))
    poll_ms = body_int(body, "poll_ms", default=DEFAULT_POLL_MS, bounds=(MIN_POLL_MS, MAX_POLL_MS))
    return WaitPlan(kind, timeout_ms, poll_ms, _WANTS[kind](body, timeout_ms))


#: Runs a look under a time limit. A name of its own so that a test can see the limit a look was given.
_within = asyncio.wait_for


async def _one(look: Looker, seconds: float) -> Look:
    """One look, abandoned when it is still running after `seconds`."""
    try:
        return await _within(look(), seconds)
    except asyncio.TimeoutError:
        raise CannotLook({"ok": False, "error": (
            f"a look at the desktop was still running {LOOK_GRACE_MS} ms after the time to wait was up, "
            "and was abandoned")}) from None


async def wait_for(plan: WaitPlan, look: Looker, *, clock: Callable[[], float] = time.monotonic,
                   sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> dict[str, Any]:
    """Look until the state is there or the time is up; the last look is at the deadline, not before it."""
    started = clock()
    give_up = started + (plan.timeout_ms + LOOK_GRACE_MS) / 1000
    polls = 0
    while True:
        seen = await _one(look, give_up - clock())
        polls += 1
        waited_ms = round((clock() - started) * 1000)
        left_ms = plan.timeout_ms - waited_ms
        if seen.done or left_ms <= 0:
            answer = {"ok": True, "happened": seen.done, "for": plan.kind, "waited_ms": waited_ms, "polls": polls}
            answer.update(seen.seen)
            return answer
        await sleep(min(plan.poll_ms, left_ms) / 1000)


__all__ = ["DEFAULT_POLL_MS", "DEFAULT_STABLE_MS", "DEFAULT_TIMEOUT_MS", "FIELDS", "LOOK_GRACE_MS", "MAX_POLL_MS",
           "MAX_TIMEOUT_MS", "MIN_POLL_MS", "REGION_BOUNDS", "REGION_FAR", "CannotLook", "Look", "Looker",
           "WaitError", "WaitPlan", "plan_wait", "wait_for"]
