"""Strong-reference lifecycle for intentionally detached asyncio work."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def spawn_background(
    coro: Coroutine[Any, Any, Any],
    *,
    on_error: Callable[[BaseException], None],
) -> asyncio.Task[Any]:
    """Schedule detached work, retain it until done, and surface failures."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)

    def finished(done: asyncio.Task[Any]) -> None:
        _BACKGROUND_TASKS.discard(done)
        if done.cancelled():
            return
        error = done.exception()
        if error is not None:
            on_error(error)

    task.add_done_callback(finished)
    return task


async def cancel_background_tasks() -> None:
    """Cancel and await detached work owned by the current event loop."""
    loop = asyncio.get_running_loop()
    tasks = tuple(task for task in _BACKGROUND_TASKS if task.get_loop() is loop)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def background_task_count() -> int:
    return len(_BACKGROUND_TASKS)
