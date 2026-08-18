"""T67: detached asyncio work must remain owned until completion."""
from __future__ import annotations

import asyncio
import gc
import json
import subprocess
import sys
import weakref
from types import SimpleNamespace
from typing import Any

from aiohttp import web

import arena.async_lifecycle as lifecycle
import arena.service.handlers as service_handlers
from arena.service.handlers import make_service_handlers


def test_background_task_is_retained_then_released() -> None:
    async def scenario() -> None:
        release = asyncio.Event()

        async def work() -> str:
            await release.wait()
            return "done"

        errors = []
        task = lifecycle.spawn_background(work(), on_error=errors.append)
        task_ref = weakref.ref(task)
        del task
        gc.collect()

        retained = task_ref()
        assert retained is not None
        assert lifecycle.background_task_count() == 1
        release.set()
        assert await retained == "done"
        await asyncio.sleep(0)
        assert lifecycle.background_task_count() == 0
        assert errors == []

    asyncio.run(scenario())


def test_background_failure_is_reported_and_released() -> None:
    async def scenario() -> None:
        errors = []

        async def fail() -> None:
            raise RuntimeError("background failed")

        task = lifecycle.spawn_background(fail(), on_error=errors.append)
        try:
            await task
        except RuntimeError:
            pass
        await asyncio.sleep(0)
        assert lifecycle.background_task_count() == 0
        assert len(errors) == 1
        assert str(errors[0]) == "background failed"

    asyncio.run(scenario())


def test_cancelled_background_task_is_not_reported_as_error() -> None:
    async def scenario() -> None:
        errors = []

        async def wait_forever() -> None:
            await asyncio.Event().wait()

        task = lifecycle.spawn_background(wait_forever(), on_error=errors.append)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
        assert lifecycle.background_task_count() == 0
        assert errors == []

    asyncio.run(scenario())


def test_cleanup_cancels_and_releases_background_tasks() -> None:
    async def scenario() -> None:
        errors = []
        started = asyncio.Event()

        async def wait_forever() -> None:
            started.set()
            await asyncio.Event().wait()

        task = lifecycle.spawn_background(wait_forever(), on_error=errors.append)
        await started.wait()
        await lifecycle.cancel_background_tasks()
        await asyncio.sleep(0)

        assert task.cancelled()
        assert lifecycle.background_task_count() == 0
        assert errors == []

    asyncio.run(scenario())


def test_ruff_rejects_discarded_task_and_accepts_retained_task(tmp_path) -> None:
    source = tmp_path / "task_lifecycle.py"
    source.write_text(
        "import asyncio\n"
        "async def work():\n    pass\n"
        "def schedule():\n    asyncio.create_task(work())\n",
        encoding="utf-8",
    )
    rejected = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--select",
            "RUF006",
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1
    assert "RUF006" in rejected.stdout

    source.write_text(
        "import asyncio\n"
        "async def work():\n    pass\n"
        "def schedule():\n    return asyncio.create_task(work())\n",
        encoding="utf-8",
    )
    accepted = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--select",
            "RUF006",
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_restart_uses_loop_owned_timer_not_detached_task(monkeypatch) -> None:
    scheduled = []

    class Loop:
        def call_later(self, delay, callback, *args):
            scheduled.append((delay, callback, args))
            return object()

    records = []
    ctx: Any = SimpleNamespace(
        require_auth=lambda _request: None,
        record_request=lambda **kwargs: records.append(kwargs),
        cors_json_response=lambda data, status=200: web.json_response(
            data, status=status
        ),
        executor=None,
        service_info_sync=lambda: {},
        sys_svc_sync=lambda: {},
        capabilities_sync=lambda: {},
        spawn_respawn_helper=lambda _port: (True, "test-helper"),
        audit=lambda event: records.append(event),
    )
    request = SimpleNamespace(app={"cfg": {"port": 9876}})
    monkeypatch.setattr(
        "arena.service.handlers.APP_CFG", "cfg"
    )
    monkeypatch.setattr(
        "arena.service.handlers.asyncio.get_running_loop", lambda: Loop()
    )
    handlers: Any = make_service_handlers(ctx)
    response = asyncio.run(handlers.restart.__wrapped__(request))
    assert response.status == 200
    assert json.loads(response.text)["respawn_scheduled"] is True
    assert len(scheduled) == 1
    delay, callback, args = scheduled[0]
    assert delay == 1.5
    assert callback is service_handlers.os._exit
    assert args == (0,)
