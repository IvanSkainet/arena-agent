"""Waiting, on the host, for the desktop to reach a state (#621)."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from arena.desktop.text_matching import normalize_text

# An agent that needed "the launcher window is up" or "the loading bar has
# stopped moving" had one way to learn it: sleep, take a screenshot, look,
# repeat -- a round trip and a step per look. A look is cheap on the host, so
# the loop lives here and the agent asks once.
#
# This module is the request and the loop. What a look *is* -- listing
# windows, comparing two captures, reading the screen -- is in `wait_looks`.

#: Under the 60 s the MCP tools wait for the bridge, with room for a last look.
MAX_TIMEOUT_MS = 45_000
DEFAULT_TIMEOUT_MS = 10_000
MIN_POLL_MS = 100
MAX_POLL_MS = 5_000
DEFAULT_POLL_MS = 500
DEFAULT_STABLE_MS = 1_000

_COMMON = ("for", "timeout_ms", "poll_ms")
_REGION = ("x", "y", "width", "height")
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


class WaitError(ValueError):
    """The request cannot be planned: the caller's mistake, a 400."""


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


def _whole(body: Mapping[str, Any], name: str, default: int, bounds: tuple[int, int]) -> int:
    """An integer field within its bounds; `true` is not a number."""
    value = body.get(name, default)
    low, high = bounds
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise WaitError(f"'{name}' must be an integer from {low} to {high}")
    return value


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
    if not isinstance(region, Mapping) or sorted(region) != sorted(_REGION):
        raise WaitError("'region' must be an object with exactly x, y, width and height")
    numbers = {name: region[name] for name in _REGION}
    if any(isinstance(n, bool) or not isinstance(n, int) for n in numbers.values()):
        raise WaitError("'region' must hold integers")
    if numbers["width"] < 1 or numbers["height"] < 1:
        raise WaitError("'region' must have a width and a height of at least 1")
    return numbers


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
    stable_ms = _whole(body, "stable_ms", usual, (MIN_POLL_MS, MAX_TIMEOUT_MS))
    if stable_ms > timeout_ms:
        raise WaitError("'stable_ms' is longer than 'timeout_ms': the screen could never be still for that long")
    want["stable_ms"] = stable_ms
    return want


def _text(body: Mapping[str, Any], _timeout_ms: int) -> dict[str, Any]:
    text = _words(body, "text")
    if not text:
        raise WaitError("a text wait needs 'text': the words to look for on the screen")
    return {"text": text, "state": _choice(body, "text", "state"), "region": _region(body),
            "min_confidence": _whole(body, "min_confidence", 40, (0, 100))}


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
    timeout_ms = _whole(body, "timeout_ms", DEFAULT_TIMEOUT_MS, (1, MAX_TIMEOUT_MS))
    poll_ms = _whole(body, "poll_ms", DEFAULT_POLL_MS, (MIN_POLL_MS, MAX_POLL_MS))
    return WaitPlan(kind, timeout_ms, poll_ms, _WANTS[kind](body, timeout_ms))


async def wait_for(plan: WaitPlan, look: Looker, *, clock: Callable[[], float] = time.monotonic,
                   sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> dict[str, Any]:
    """Look until the state is there or the time is up; the last look is at the deadline, not before it."""
    started = clock()
    polls = 0
    while True:
        seen = await look()
        polls += 1
        waited_ms = round((clock() - started) * 1000)
        left_ms = plan.timeout_ms - waited_ms
        if seen.done or left_ms <= 0:
            answer = {"ok": True, "happened": seen.done, "for": plan.kind, "waited_ms": waited_ms, "polls": polls}
            answer.update(seen.seen)
            return answer
        await sleep(min(plan.poll_ms, left_ms) / 1000)


__all__ = ["DEFAULT_POLL_MS", "DEFAULT_STABLE_MS", "DEFAULT_TIMEOUT_MS", "FIELDS", "MAX_POLL_MS", "MAX_TIMEOUT_MS",
           "MIN_POLL_MS", "CannotLook", "Look", "Looker", "WaitError", "WaitPlan", "plan_wait", "wait_for"]
