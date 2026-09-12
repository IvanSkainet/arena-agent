"""The concurrency gate answers 429 instead of going quiet (#333).

Found by the fuzz gate, not by a person: one request in ~4800 came back
as `Read timed out after 10.0 seconds` against the bridge that
`scripts/serve_bridge_for_fuzzing.py` serves. The two defects behind it
are tested separately here because they fail for different reasons and
either one alone reproduces the timeout.

Kept out of the other exec test modules on purpose: CodeScene reads a
file mixing unrelated subjects as low cohesion, and this one is about
capacity alone.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import sys
import time
from pathlib import Path

import pytest

from arena.app_keys import APP_CFG
from tests._live_bridge import MAX_CONCURRENT, auth_header, running_client

TOKEN = "t" * 43


# The script endpoint runs a real interpreter, so the body has to be one
# that exists on every runner. `sh` does not on Windows -- the first
# revision of these two tests used it and got 400 ("interpreter not
# available") from all five Windows jobs, which reads as "no 429" and
# fails the assertion for the wrong reason. `node`, `python3` and `pwsh`
# are platform "any" too (cubic); `python` is chosen because it is the
# one guaranteed present on every runner -- the suite is running in it.
SCRIPT_INTERPRETER = "python"
SLOW_SCRIPT = b"import time\ntime.sleep(2)\n"

# `sleep 2` is not a command on Windows: the live run there returned it in
# 0.02s, every "accepted" request finished instantly, and the relative
# timing assertion below had nothing to compare against. The interpreter
# running the suite is the one thing guaranteed present on every runner,
# and quoting handles a path with spaces (`C:\Program Files\...`).
SLOW_COMMAND = f'"{sys.executable}" -c "import time; time.sleep(2)"'


def _script_headers(cwd: Path) -> dict[str, str]:
    headers = dict(auth_header(TOKEN))
    headers["X-Arena-Interpreter"] = SCRIPT_INTERPRETER
    headers["X-Arena-Cwd"] = str(cwd)
    return headers


def _assert_refused_without_queueing(
        refusal: float, accepted: list[float]) -> None:
    """The refusal must be quick *relative to* the work it refused.

    An absolute bound would be a timing assertion on a shared CI runner,
    which is how #320, #337 and #343 all started (cubic). The accepted
    requests sleep for two seconds, so a refusal that queued behind one
    is unmistakable next to them, however slow the machine is.
    """
    assert accepted, "nothing was accepted, so there is no baseline"
    # The baseline has to be real work. On Windows `sleep 2` is not a
    # command, so the accepted requests came back in 0.02s and the
    # comparison below was between two instant numbers -- it passed
    # locally and failed on the live Windows run for reasons that had
    # nothing to do with queueing. A baseline that fast means the
    # command did not run, which is its own bug and says so.
    assert min(accepted) > 0.5, (
        f"the accepted work finished in {min(accepted):.2f}s -- it never "
        f"ran, so there is nothing to compare a refusal against")
    assert refusal < min(accepted) / 2, (
        f"the refusal took {refusal:.2f}s against accepted work at "
        f"{min(accepted):.2f}s -- it queued rather than being refused")


async def _status_and_duration(client, path: str, cmd: str) -> tuple[int, float]:
    started = time.monotonic()
    response = await client.post(
        path, headers=auth_header(TOKEN), json={"cmd": cmd, "cwd": str(client.app[APP_CFG]["root"])})
    await response.text()
    return response.status, time.monotonic() - started


@pytest.mark.parametrize("path", ["/v1/exec", "/v1/exec/stream"])
def test_a_request_over_capacity_is_refused_not_parked(
        tmp_path: Path, path: str) -> None:
    """Over capacity must mean a fast 429, never a silent wait.

    The old gate needed `sem.locked() and active_exec >= max_concurrent`
    -- two accounts of the same thing, with nothing keeping them in step.
    When they disagreed the `and` never held, so the refusal was
    unreachable and the request queued on `acquire()` instead. A caller
    cannot retry or back off against silence; it just times out.
    """
    asyncio.run(_over_capacity_is_refused(tmp_path, path))


async def _over_capacity_is_refused(tmp_path: Path, path: str) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        busy = [
            asyncio.create_task(_status_and_duration(client, path, SLOW_COMMAND))
            for _ in range(MAX_CONCURRENT + 1)
        ]
        results = await asyncio.gather(*busy)

    refused = [(status, seconds) for status, seconds in results if status == 429]
    accepted = [seconds for status, seconds in results if status == 200]
    assert len(refused) == 1, results
    _assert_refused_without_queueing(refused[0][1], accepted)


def test_capacity_is_one_number_not_two(tmp_path: Path) -> None:
    """The semaphore and the limit must describe the same bridge.

    This is the half that made the fuzz run time out. The bridge was
    built with `max_concurrent: 3` and `Semaphore(1)`, so `active_exec`
    could never reach 3, the gate could never fire, and four concurrent
    requests came back as four 200s at 1.01, 2.02, 3.02 and 4.03 seconds
    -- a queue, from a server that advertises a refusal.
    """
    asyncio.run(_capacity_agrees(tmp_path))


async def _capacity_agrees(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        cfg = client.app[APP_CFG]
        semaphore: asyncio.Semaphore = cfg["semaphore"]
        assert semaphore._value == cfg["max_concurrent"], (  # noqa: SLF001
            f"semaphore admits {semaphore._value}, gate compares against "  # noqa: SLF001
            f"{cfg['max_concurrent']}")


def test_the_slot_is_returned_after_every_outcome(tmp_path: Path) -> None:
    """Capacity must survive failures, not only clean runs.

    A slot released on the success path alone leaks one per failure, and
    a bridge that has leaked `max_concurrent` of them refuses everything
    forever while looking idle.
    """
    asyncio.run(_slots_come_back(tmp_path))


async def _slots_come_back(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        cfg = client.app[APP_CFG]
        for cmd in ("exit 3", "nosuchcommand-333", "echo fine"):
            for _ in range(MAX_CONCURRENT + 2):
                await _status_and_duration(client, "/v1/exec", cmd)
        assert cfg["active_exec"] == 0, cfg["active_exec"]

        results = await asyncio.gather(*[
            _status_and_duration(client, "/v1/exec", SLOW_COMMAND)
            for _ in range(MAX_CONCURRENT)
        ])

    assert [status for status, _ in results] == [200] * MAX_CONCURRENT, results


@pytest.mark.parametrize("path", ["/v1/exec", "/v1/exec/stream"])
def test_the_refusal_does_not_depend_on_the_counter_agreeing(
        tmp_path: Path, path: str) -> None:
    """The gate must hold even when the two numbers disagree again.

    The pair of defects here was a lesson from #211 repeated: fixing the
    config made the old `sem.locked() and active_exec >= max_concurrent`
    gate pass every test above, because with the numbers in step the
    `and` happens to be right. That is a test of the config, not of the
    gate -- and the config is one careless edit away from drifting back.

    So this one drives the disagreement deliberately: capacity of one,
    `max_concurrent` claiming a hundred. The old gate cannot fire under
    those numbers and parks the second request until the first finishes.
    Asking only the semaphore, the answer is a 429 either way.
    """
    asyncio.run(_refusal_survives_disagreement(tmp_path, path))


async def _refusal_survives_disagreement(tmp_path: Path, path: str) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        cfg = client.app[APP_CFG]
        cfg["semaphore"] = asyncio.Semaphore(1)
        cfg["max_concurrent"] = 100
        cfg["active_exec"] = 0

        results = await asyncio.gather(*[
            _status_and_duration(client, path, SLOW_COMMAND) for _ in range(2)
        ])

    refused = [(status, seconds) for status, seconds in results if status == 429]
    accepted = [seconds for status, seconds in results if status == 200]
    assert len(refused) == 1, (
        f"capacity is 1, so the second request must be refused: {results}")
    _assert_refused_without_queueing(refused[0][1], accepted)


def test_the_script_endpoint_shares_the_same_refusal(tmp_path: Path) -> None:
    """/v1/exec/script is the third copy of the gate, and it drifted too.

    It shares the semaphore with /v1/exec deliberately, so the two
    endpoints share fairness rather than doubling capacity -- which also
    means a request over the shared limit has to be refused here in the
    same breath, and before the script body is staged on disk.
    """
    asyncio.run(_script_refuses_over_capacity(tmp_path))


async def _script_refuses_over_capacity(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        headers = _script_headers(tmp_path)

        async def run_script() -> tuple[int, float]:
            started = time.monotonic()
            response = await client.post(
                "/v1/exec/script", headers=headers, data=SLOW_SCRIPT)
            await response.text()
            return response.status, time.monotonic() - started

        results = await asyncio.gather(*[
            asyncio.create_task(run_script())
            for _ in range(MAX_CONCURRENT + 1)
        ])

        staged = tmp_path / ".arena_script_tmp"
        leftovers = list(staged.iterdir()) if staged.exists() else []

    # Checked before the count: a 400 from an interpreter the runner does
    # not have reads as "no 429 seen" and fails the real assertion with a
    # misleading message. That is exactly how the first revision of this
    # test failed on Windows.
    assert {status for status, _ in results} <= {200, 429}, (
        f"the script never ran -- interpreter unavailable? {results}")
    refused = [(status, seconds) for status, seconds in results if status == 429]
    accepted = [seconds for status, seconds in results if status == 200]
    assert len(refused) == 1, results
    _assert_refused_without_queueing(refused[0][1], accepted)
    assert not leftovers, f"a refused script left files behind: {leftovers}"


def test_the_script_refusal_also_survives_a_disagreement(tmp_path: Path) -> None:
    """The same drift check for the third copy of the gate.

    Without it the script endpoint passes every test above while still
    carrying the old `and`, because those tests run with the two numbers
    in step -- verified by mutation: restoring the old gate here broke
    nothing until this test existed.
    """
    asyncio.run(_script_refusal_survives_disagreement(tmp_path))


async def _script_refusal_survives_disagreement(tmp_path: Path) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        cfg = client.app[APP_CFG]
        cfg["semaphore"] = asyncio.Semaphore(1)
        cfg["max_concurrent"] = 100
        cfg["active_exec"] = 0

        headers = _script_headers(tmp_path)

        async def run_script() -> tuple[int, float]:
            started = time.monotonic()
            response = await client.post(
                "/v1/exec/script", headers=headers, data=SLOW_SCRIPT)
            await response.text()
            return response.status, time.monotonic() - started

        results = await asyncio.gather(*[
            asyncio.create_task(run_script()) for _ in range(2)
        ])

    assert {status for status, _ in results} <= {200, 429}, (
        f"the script never ran -- interpreter unavailable? {results}")
    refused = [(status, seconds) for status, seconds in results if status == 429]
    accepted = [seconds for status, seconds in results if status == 200]
    assert len(refused) == 1, (
        f"capacity is 1, so the second script must be refused: {results}")
    _assert_refused_without_queueing(refused[0][1], accepted)


def test_a_blocked_script_does_not_keep_the_slot(tmp_path: Path) -> None:
    """A refusal after the acquire must still give the permit back.

    cubic, P1: the slot was taken before `ctx.blocked_reason` ran, and
    that check's 403 returns through a path written when the acquire was
    still further down. Measured on that code -- `active_exec` climbing
    1, 2, 3 over three blocked scripts and staying there, with every
    later exec answered 429 for the life of the process.

    A leak that only capacity reveals, which is why this asserts the
    counter directly and then proves the bridge still works.
    """
    asyncio.run(_blocked_scripts_do_not_leak(tmp_path))


async def _blocked_scripts_do_not_leak(tmp_path: Path) -> None:
    import gc

    from arena.handler_context import ExecHandlerContext

    async with running_client(tmp_path, TOKEN) as client:
        cfg = client.app[APP_CFG]
        contexts = [
            obj for obj in gc.get_objects()
            if isinstance(obj, ExecHandlerContext)
        ]
        assert contexts, "no ExecHandlerContext to reach the blocklist through"
        # Put each original back afterwards rather than replacing it with
        # an allow-all stand-in: these are live objects reached through
        # `gc`, and leaving a different callback behind is a change this
        # test has no business making (cubic).
        originals = [(c, c.blocked_reason) for c in contexts]
        for context in contexts:
            object.__setattr__(
                context, "blocked_reason", lambda _cmd: "blocked for the test")

        try:
            headers = _script_headers(tmp_path)
            for _ in range(MAX_CONCURRENT + 2):
                response = await client.post(
                    "/v1/exec/script", headers=headers, data=SLOW_SCRIPT)
                await response.text()
                assert response.status == 403, response.status
                assert cfg["active_exec"] == 0, (
                    f"a blocked script kept the slot: active_exec="
                    f"{cfg['active_exec']}")
        finally:
            for context, original in originals:
                object.__setattr__(context, "blocked_reason", original)

        status, _ = await _status_and_duration(client, "/v1/exec", "echo ok")

    assert status == 200, f"the bridge was exhausted by refusals: {status}"


def test_a_failed_stream_prepare_does_not_keep_the_slot(tmp_path: Path) -> None:
    """The same leak on the streaming path, through failing I/O.

    cubic, P1: `response.prepare()` runs after the acquire and can fail.
    Measured before the fix -- five failed prepares took a capacity-three
    bridge to zero and /v1/exec answered 429 to an ordinary request.
    """
    asyncio.run(_failed_prepare_does_not_leak(tmp_path))


async def _failed_prepare_does_not_leak(tmp_path: Path) -> None:
    from aiohttp import web

    original = web.StreamResponse.prepare

    async with running_client(tmp_path, TOKEN) as client:
        cfg = client.app[APP_CFG]
        # Count the prepares that actually raised. Suppressing the
        # exception and never looking at the status let this test pass
        # while exercising nothing at all -- if the monkeypatch stops
        # applying, every stream succeeds and the leak goes unmeasured
        # (cubic).
        refused = 0

        async def counting_refusal(self, request):  # noqa: ANN001, ARG001
            nonlocal refused
            refused += 1
            raise RuntimeError("prepare failed")

        web.StreamResponse.prepare = counting_refusal
        try:
            for _ in range(MAX_CONCURRENT + 2):
                with contextlib.suppress(Exception):
                    response = await client.post(
                        "/v1/exec/stream", headers=auth_header(TOKEN),
                        json={"cmd": "echo hi", "cwd": str(tmp_path)})
                    await response.text()
                assert cfg["active_exec"] == 0, (
                    f"a failed prepare kept the slot: active_exec="
                    f"{cfg['active_exec']}")
        finally:
            web.StreamResponse.prepare = original

        # At least once per request -- aiohttp also prepares the 500 it
        # builds after the handler raises, so the count runs ahead of the
        # request count. The point is that it is not zero.
        assert refused >= MAX_CONCURRENT + 2, (
            f"the injected prepare failure fired {refused} times for "
            f"{MAX_CONCURRENT + 2} requests: the test measured nothing")

        status, _ = await _status_and_duration(client, "/v1/exec", "echo ok")

    assert status == 200, f"the bridge was exhausted by failed streams: {status}"


def test_a_failed_cleanup_is_audited_not_swallowed(tmp_path: Path) -> None:
    """A staged script that cannot be deleted leaves a record.

    cubic/corgea: the cleanup caught every exception and passed, so a
    permission or filesystem error left files accumulating with no
    diagnostic at all.
    """
    asyncio.run(_failed_cleanup_is_audited(tmp_path))


async def _failed_cleanup_is_audited(tmp_path: Path) -> None:
    import gc

    from arena.handler_context import ExecHandlerContext

    real_unlink = os.unlink

    def refuses_to_unlink(path, *args, **kwargs):  # noqa: ANN001, ANN202
        if ".arena_script_tmp" in str(path):
            raise PermissionError("cleanup refused for the test")
        return real_unlink(path, *args, **kwargs)

    async with running_client(tmp_path, TOKEN) as client:
        contexts = [
            obj for obj in gc.get_objects()
            if isinstance(obj, ExecHandlerContext)
        ]
        assert contexts, "no ExecHandlerContext to watch the audit through"
        events: list[dict] = []
        originals = [(c, c.audit) for c in contexts]

        def recording_audit(event: dict, _original=originals[0][1]) -> None:
            events.append(event)
            _original(event)

        for context in contexts:
            object.__setattr__(context, "audit", recording_audit)
        os.unlink = refuses_to_unlink
        response = None
        try:
            response = await client.post(
                "/v1/exec/script", headers=_script_headers(tmp_path),
                data=b"print('hi')\n")
            await response.text()
        finally:
            os.unlink = real_unlink
            for context, original in originals:
                object.__setattr__(context, "audit", original)

        assert response is not None, "the request never returned a response"
        assert response.status == 200, response.status
        failures = [e for e in events
                    if e.get("type") == "exec_script_cleanup_failed"]
        assert failures, (
            "a cleanup that raised produced no audit record: "
            f"{[e.get('type') for e in events]}")
        assert "PermissionError" in failures[0]["error"], failures[0]


def test_an_audit_that_raises_does_not_replace_the_response(
        tmp_path: Path) -> None:
    """A broken audit log must not turn a good run into a 500.

    cubic: the cleanup audit writes to a file and sits in a `finally`,
    where a raise is delivered instead of the pending return.
    """
    asyncio.run(_audit_failure_does_not_replace_response(tmp_path))


async def _audit_failure_does_not_replace_response(tmp_path: Path) -> None:
    import gc

    from arena.handler_context import ExecHandlerContext

    real_unlink = os.unlink

    def refuses_to_unlink(path, *args, **kwargs):  # noqa: ANN001, ANN202
        if ".arena_script_tmp" in str(path):
            raise PermissionError("cleanup refused for the test")
        return real_unlink(path, *args, **kwargs)

    def refuses_to_audit(event: dict, _original=None) -> None:
        # Only the cleanup audit: breaking every audit call would fail the
        # run somewhere earlier and prove nothing about the `finally`.
        if event.get("type") == "exec_script_cleanup_failed":
            raise OSError("audit log is unwritable")
        if _original is not None:
            _original(event)

    async with running_client(tmp_path, TOKEN) as client:
        contexts = [
            obj for obj in gc.get_objects()
            if isinstance(obj, ExecHandlerContext)
        ]
        assert contexts, "no ExecHandlerContext to break the audit on"
        originals = [(c, c.audit) for c in contexts]
        for context, original in originals:
            object.__setattr__(
                context, "audit",
                functools.partial(refuses_to_audit, _original=original))
        os.unlink = refuses_to_unlink
        response = None
        try:
            response = await client.post(
                "/v1/exec/script", headers=_script_headers(tmp_path),
                data=b"print('hi')\n")
            await response.text()
        finally:
            os.unlink = real_unlink
            for context, original in originals:
                object.__setattr__(context, "audit", original)

    assert response is not None, "the request never returned a response"
    assert response.status == 200, (
        f"an unwritable audit log turned a successful run into "
        f"{response.status}")
