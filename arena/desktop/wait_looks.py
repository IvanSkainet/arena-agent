"""What one look is, for each kind of desktop wait (#621)."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from arena.desktop.availability import MissingTool, unavailable_result
from arena.desktop.frame_compare import Frame, compared_as, read_frame
from arena.desktop.wait import CannotLook, Look, Looker
from arena.desktop.window_catalog import window_candidates

# Each maker takes what the plan wants and the producers it may ask, and
# returns the look the loop in `wait.py` repeats. A look answers "is it
# there yet", and raises `CannotLook` when the desktop could not be asked --
# which is not the same as "no", and must not be reported as a wait that
# simply ran out of time.

Region = dict[str, int] | None
_NO_LISTING = MissingTool(
    "no tool to list windows: install wmctrl or xdotool, or run a desktop whose window list the bridge can read",
    ("wmctrl", "xdotool"))
_NO_CROP = MissingTool(
    "the capture could not be cut to the region, so it shows the whole desktop: on this host that needs the "
    "Pillow package (pip install Pillow)", ("pillow",))


def _matching(windows: list[dict[str, Any]], want: Mapping[str, Any]) -> list[dict[str, Any]]:
    return window_candidates(windows, title=want["title"], class_contains=want["class"])


def _listed(listing: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The windows of a listing, or `CannotLook` when nothing listed them."""
    if not listing.get("ok"):
        raise CannotLook(listing)
    if listing.get("tool") == "none":
        # "No windows" from a desktop with no way to list them would make
        # every wait for a window to go away succeed at once.
        raise CannotLook(unavailable_result(_NO_LISTING))
    return list(listing.get("windows") or [])


def _cut_to(region: Region, result: Mapping[str, Any]) -> None:
    """Refuse a capture that shows more than the region asked for.

    Where the capture tool takes the whole desktop, Pillow cuts the region out
    of it; without Pillow the whole picture comes back, with nothing in
    `captured_region`. Watching that instead would answer for a place the
    caller did not ask about.
    """
    if region and not result.get("captured_region"):
        raise CannotLook(unavailable_result(_NO_CROP))


def _present(hits: list[dict[str, Any]]) -> Look:
    return Look(bool(hits), {"matches": len(hits), "window": hits[0]} if hits else {"matches": 0})


def _absent(hits: list[dict[str, Any]]) -> Look:
    return Look(not hits, _present(hits).seen)


def window_look(want: Mapping[str, Any], list_windows: Callable[[], Awaitable[Mapping[str, Any]]],
                active_window: Callable[[], Awaitable[dict[str, Any] | None]]) -> Looker:
    """A window is there, is gone, or is the one in front."""

    async def in_front() -> Look:
        front = await active_window()
        if front is None:
            # Nothing in front, or no way to tell? A desktop whose windows
            # cannot be listed is the second, and waiting would not change it.
            _listed(await list_windows())
        if _matching([front] if front else [], want):
            return Look(True, {"window": front})
        # What is in front instead is the first thing the caller will ask.
        return Look(False, {"active_window": front})

    async def listed() -> Look:
        hits = _matching(_listed(await list_windows()), want)
        return _present(hits) if want["state"] == "present" else _absent(hits)

    return in_front if want["state"] == "active" else listed


async def _frame(capture: Callable[[Region], Awaitable[Mapping[str, Any]]], region: Region) -> Frame:
    shot = await capture(region)
    if not shot.get("ok"):
        raise CannotLook(shot)
    _cut_to(region, shot)
    # Off the event loop: inflating a full-screen capture takes tens of milliseconds.
    return await asyncio.to_thread(read_frame, shot["bytes"])


def screen_look(want: Mapping[str, Any], capture: Callable[[Region], Awaitable[Mapping[str, Any]]],
                clock: Callable[[], float] = time.monotonic) -> Looker:
    """The picture differs from the first look, or has not differed for `stable_ms`."""
    first: list[Frame] = []
    last: list[Any] = []  # [frame, the clock when it was first seen]

    async def change() -> Look:
        frame = await _frame(capture, want["region"])
        if not first:
            first.append(frame)
        return Look(frame.digest != first[0].digest, {"compared": compared_as(first[0], frame)})

    async def stable() -> Look:
        frame = await _frame(capture, want["region"])
        now = clock()
        if not last or frame.digest != last[0].digest:
            last[:] = [frame, now]
        still_ms = round((now - last[1]) * 1000)
        return Look(still_ms >= want["stable_ms"], {"still_ms": still_ms, "compared": compared_as(last[0], frame)})

    return change if want["until"] == "change" else stable


def text_look(want: Mapping[str, Any],
              find_text: Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]) -> Looker:
    """The words are on the screen, or no longer are."""

    async def look() -> Look:
        result = await find_text(want)
        if not result.get("ok"):
            raise CannotLook(result)
        _cut_to(want["region"], result)
        matches = list(result.get("matches") or [])
        seen: dict[str, Any] = {"matches": len(matches), "word_count": result.get("word_count", 0)}
        if matches:
            seen["match"] = matches[0]
        return Look(bool(matches) == (want["state"] == "present"), seen)

    return look


__all__ = ["Region", "screen_look", "text_look", "window_look"]
