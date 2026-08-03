"""The CDP error-logging callback must survive being called.

`CDPTabManagerCallbackMixin._log_callback_error` is handed to
`Task.add_done_callback(...)` from three sites in
`tab_manager_targets.py`. It was declared as a plain method whose first
parameter is named ``task``:

    def _log_callback_error(task: asyncio.Task) -> None:

Accessed as ``self._log_callback_error`` that becomes a *bound* method, so
``self`` lands in the ``task`` slot and the real Task has nowhere to go. Every
invocation raised TypeError, asyncio routed it to the loop exception handler,
and the outcome was that errors from fire-and-forget CDP callback tasks were
never logged -- by the one function whose entire job that was.

Found because declaring the mixin interfaces made pyrefly able to see the
call shape at all (`invalid-annotation`: "self type `Task` is not a superclass
of `CDPTabManagerCallbackMixin`").

These tests call the thing rather than inspecting it, because "no exception was
raised somewhere else" was exactly the broken state.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.browser.cdp_client.tab_manager_callbacks import (  # noqa: E402
    CDPTabManagerCallbackMixin,
)


class _Manager(CDPTabManagerCallbackMixin):
    """Minimal concrete user of the mixin."""


def _run(coro):
    loop = asyncio.new_event_loop()
    problems: list[str] = []
    loop.set_exception_handler(lambda _l, ctx: problems.append(str(ctx.get("message"))))
    try:
        loop.run_until_complete(coro(loop))
    finally:
        loop.close()
    return problems


def test_done_callback_does_not_raise_when_bound():
    """The regression itself: binding must not eat the Task argument."""
    async def scenario(_loop):
        mgr = _Manager()
        task = asyncio.ensure_future(asyncio.sleep(0))
        task.add_done_callback(mgr._log_callback_error)
        await asyncio.sleep(0.05)

    problems = _run(scenario)
    assert problems == [], f"callback blew up: {problems}"


def test_it_actually_logs_a_failing_task():
    """Not just 'no crash' -- the error must reach the log."""
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = Capture()
    logger = logging.getLogger("cdp_browser")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)

    async def scenario(_loop):
        mgr = _Manager()

        async def boom():
            raise RuntimeError("callback exploded")

        task = asyncio.ensure_future(boom())
        task.add_done_callback(mgr._log_callback_error)
        await asyncio.sleep(0.05)

    try:
        problems = _run(scenario)
    finally:
        logger.removeHandler(handler)

    assert problems == [], f"loop reported: {problems}"
    assert any("callback exploded" in r or "callback task error" in r.lower()
               for r in records), f"the failure was never logged: {records}"


def test_a_cancelled_task_is_not_reported_as_an_error():
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = Capture()
    logger = logging.getLogger("cdp_browser")
    logger.addHandler(handler)

    async def scenario(_loop):
        mgr = _Manager()
        task = asyncio.ensure_future(asyncio.sleep(10))
        task.cancel()
        task.add_done_callback(mgr._log_callback_error)
        await asyncio.sleep(0.05)

    try:
        problems = _run(scenario)
    finally:
        logger.removeHandler(handler)

    assert problems == []
    assert records == [], f"cancellation logged as an error: {records}"


def test_the_callback_stays_a_staticmethod():
    """Dropping @staticmethod silently reintroduces the bug."""
    attr = inspect.getattr_static(CDPTabManagerCallbackMixin, "_log_callback_error")
    assert isinstance(attr, staticmethod), (
        "_log_callback_error is bound again; `self` will occupy the task slot"
    )


@pytest.mark.parametrize("module", [
    "arena.browser.cdp_client.tab_manager_targets",
])
def test_call_sites_still_pass_it_as_a_done_callback(module):
    """If the call shape changes, this gate should be revisited, not ignored."""
    src = Path(REPO / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8")
    assert "add_done_callback(self._log_callback_error)" in src
