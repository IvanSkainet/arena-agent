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
# fails the assertion for the wrong reason. `python` is the only entry
# in the interpreter table with platform "any".
SCRIPT_INTERPRETER = "python"
SLOW_SCRIPT = b"import time\ntime.sleep(2)\n"


def _script_headers(cwd: Path) -> dict[str, str]:
    headers = dict(auth_header(TOKEN))
    headers["X-Arena-Interpreter"] = SCRIPT_INTERPRETER
    headers["X-Arena-Cwd"] = str(cwd)
    return headers


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
            asyncio.create_task(_status_and_duration(client, path, "sleep 2"))
            for _ in range(MAX_CONCURRENT + 1)
        ]
        results = await asyncio.gather(*busy)

    refused = [(status, seconds) for status, seconds in results if status == 429]
    assert len(refused) == 1, results
    assert refused[0][1] < 1.0, f"the refusal took {refused[0][1]:.2f}s"


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
            _status_and_duration(client, "/v1/exec", "sleep 1")
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
            _status_and_duration(client, path, "sleep 2") for _ in range(2)
        ])

    refused = [(status, seconds) for status, seconds in results if status == 429]
    assert len(refused) == 1, (
        f"capacity is 1, so the second request must be refused: {results}")
    assert refused[0][1] < 1.0, (
        f"the refusal waited {refused[0][1]:.2f}s -- it queued instead")


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
    assert len(refused) == 1, results
    assert refused[0][1] < 1.0, f"the refusal took {refused[0][1]:.2f}s"
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
    assert len(refused) == 1, (
        f"capacity is 1, so the second script must be refused: {results}")
    assert refused[0][1] < 1.0, (
        f"the refusal waited {refused[0][1]:.2f}s -- it queued instead")
