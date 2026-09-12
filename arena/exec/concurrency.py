"""The concurrency slot behind /v1/exec and its two siblings (#333).

Lifted out of `arena/exec/handlers.py` to keep that module under the
mini-monolith threshold, and because three handlers share this and none
of them owns it.
"""
from __future__ import annotations

import asyncio

from aiohttp import web

from arena.handler_helpers import err_json

__all__ = ["ExecSlot", "too_many_concurrent"]


class ExecSlot:
    """A concurrency slot, taken without blocking or not at all (#333).

    The gate this replaces asked two questions and trusted the answer to
    both:

        if sem.locked() and cfg["active_exec"] >= cfg["max_concurrent"]:
            return 429
        await sem.acquire()

    `sem` and `active_exec` are separate accounts of the same thing, and
    nothing keeps them in step. Where the semaphore was built smaller than
    `max_concurrent` -- which is how the fuzzing bridge is configured, and
    how the fuzz gate found this -- `active_exec` never reaches the
    threshold, so the `and` is never true, so 429 is unreachable and
    every request over capacity queues on `acquire` instead. Measured on
    that config with four concurrent requests: four 200s at 1.01, 2.02,
    3.02 and 4.03 seconds, no 429. A client with a 10-second timeout gets
    silence rather than an answer it can act on.

    Asking the semaphore itself, and only it, removes the disagreement:
    a slot is free or it is not, and "not" is a 429 rather than a wait.
    `active_exec` survives as the number `/v1/system` reports, now
    maintained by this object rather than by each handler.
    """

    __slots__ = ("_cfg", "_sem", "_held")

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self._sem: asyncio.Semaphore = cfg["semaphore"]
        self._held = False

    async def try_acquire(self) -> bool:
        """Take a slot if one is free right now, never waiting for it.

        `locked()` is documented as "cannot be acquired immediately", so
        on the False branch `acquire()` takes its fast path -- decrement
        and return -- without ever awaiting. A coroutine that does not
        await does not yield to the event loop, so no other task can slip
        in and take the slot between the check and the acquire. That is
        what makes this pair atomic without touching the semaphore's
        internals.
        """
        if self._sem.locked():
            return False
        await self._sem.acquire()
        self._held = True
        self._cfg["active_exec"] += 1
        return True

    def release(self) -> None:
        """Give the slot back; safe to call when none was taken."""
        if not self._held:
            return
        self._held = False
        self._cfg["active_exec"] -= 1
        self._sem.release()


def too_many_concurrent(ctx, request_id: str) -> web.Response:
    """The 429 every over-capacity exec request now actually receives."""
    ctx.record_request(is_error=True, count_request=False)
    return err_json(ctx, "too many concurrent exec requests",
                    status=429, request_id=request_id)
