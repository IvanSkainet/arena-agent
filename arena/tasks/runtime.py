"""Task queue runtime compatibility wrappers."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.tasks.queue import clean_tasks, list_tasks, submit_task


@dataclass(frozen=True)
class TaskQueueRuntimeContext:
    inbox: Path
    running: Path
    done: Path
    failed: Path
    default_cwd: str
    now: Callable[[], str]


@dataclass(frozen=True)
class TaskQueueRuntime:
    tasks_list_sync: Callable[[str, int], dict[str, Any]]
    task_submit_sync: Callable[[dict[str, Any]], dict[str, Any]]
    tasks_clean_sync: Callable[[], dict[str, Any]]


def make_task_queue_runtime(ctx: TaskQueueRuntimeContext) -> TaskQueueRuntime:
    def _tasks_list_sync(status: str, limit: int) -> dict[str, Any]:
        return list_tasks(inbox=ctx.inbox, running=ctx.running, done=ctx.done, failed=ctx.failed, status=status, limit=limit)

    def _task_submit_sync(data: dict[str, Any]) -> dict[str, Any]:
        return submit_task(data, inbox=ctx.inbox, default_cwd=ctx.default_cwd, now_fn=ctx.now)

    def _tasks_clean_sync() -> dict[str, Any]:
        return clean_tasks(done=ctx.done, failed=ctx.failed, older_than_seconds=86400)

    return TaskQueueRuntime(
        tasks_list_sync=_tasks_list_sync,
        task_submit_sync=_task_submit_sync,
        tasks_clean_sync=_tasks_clean_sync,
    )
