"""Two rotations at once must not diverge memory from disk (#211).

The write runs in an eight-worker executor, so two authenticated requests
overlap freely. Unserialised, the executor can finish A last while B
installs itself into `cfg["token"]`, leaving the live credential and the
token file holding different values -- measured on the unlocked code, two
runs in six. Nothing looks wrong until the bridge restarts and reads the
file, at which point every client is locked out. That is the same failure
`test_token_regenerate_status_211.py` is about, arrived at from
concurrency rather than from a write error.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from tests._live_bridge import auth_header, json_payload, running_client

TOKEN = "token-regenerate-status-211"


# ---------------------------------------------------------------------------
# Concurrent rotations (CodeRabbit, Major)
# ---------------------------------------------------------------------------

def test_overlapping_rotations_leave_memory_and_disk_agreeing(
        tmp_path: Path) -> None:
    """The same divergence as #211, reached from the other direction.

    The write runs in an eight-worker executor, so two authenticated
    requests overlap freely. Unserialised, the executor can finish A last
    while B installs itself into `cfg["token"]`, leaving the live
    credential and the token file holding different values -- measured on
    the unlocked code: two runs in six diverged. Nothing is wrong until the
    bridge restarts and reads the file, at which point every client is
    locked out, which is exactly the outcome this PR exists to prevent.
    """
    asyncio.run(_overlapping_rotations_agree(tmp_path))


async def _overlapping_rotations_agree(tmp_path: Path) -> None:
    from arena.app_keys import APP_CFG

    async with running_client(tmp_path, TOKEN) as client:
        client.app[APP_CFG]["token_file"] = str(tmp_path / "token.txt")
        responses = await asyncio.gather(*[
            client.post("/v1/token/regenerate", headers=auth_header(TOKEN))
            for _ in range(8)])
        handed_out = []
        for response in responses:
            payload = await json_payload(response)
            assert response.status == 200, payload
            handed_out.append(payload["token"])
        in_memory = client.app[APP_CFG]["token"]
        on_disk = (tmp_path / "token.txt").read_text(encoding="utf-8").strip()

    assert in_memory == on_disk, (
        "the live credential and the token file diverged, so the next "
        "restart locks every client out")
    assert in_memory in handed_out, (
        "the surviving token was never handed to any caller")


def test_rotations_do_not_overlap_each_other(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Serialisation stated directly, because the race is probabilistic.

    `test_overlapping_rotations_leave_memory_and_disk_agreeing` asserts the
    outcome, and the outcome only diverges on unlucky interleavings -- it
    caught the unlocked code two runs in three. This one records when each
    rotation enters and leaves the executor and asserts the intervals do
    not overlap, which fails every time the lock is absent.
    """
    asyncio.run(_rotations_do_not_overlap(tmp_path, monkeypatch))


async def _rotations_do_not_overlap(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from arena.admin import token_rotation as admin_handlers

    real = admin_handlers.token_regenerate
    live = {"n": 0}
    overlaps: list[int] = []

    def slow(*args, **kwargs):
        live["n"] += 1
        if live["n"] > 1:
            overlaps.append(live["n"])
        time.sleep(0.05)
        try:
            return real(*args, **kwargs)
        finally:
            live["n"] -= 1

    monkeypatch.setattr(admin_handlers, "token_regenerate", slow)

    async with running_client(tmp_path, TOKEN) as client:
        from arena.app_keys import APP_CFG

        client.app[APP_CFG]["token_file"] = str(tmp_path / "token.txt")
        await asyncio.gather(*[
            client.post("/v1/token/regenerate", headers=auth_header(TOKEN))
            for _ in range(4)])

    assert not overlaps, (
        f"{len(overlaps)} rotation(s) ran while another was in flight; "
        "the write and the in-memory install are not serialised")


def test_the_rotation_lock_is_per_application(tmp_path: Path) -> None:
    """Two bridges in one process must not serialise against each other.

    The lock is stored on the aiohttp application rather than the module
    for this reason; a module-level lock would make the test rig's
    concurrent bridges contend and would be a real bottleneck for anyone
    running more than one.
    """
    from aiohttp import web

    from arena.admin.token_rotation import _rotation_lock_for

    first, second = web.Application(), web.Application()

    assert _rotation_lock_for(first) is _rotation_lock_for(first)
    assert _rotation_lock_for(first) is not _rotation_lock_for(second)


def test_the_200_schema_requires_the_note_the_handler_always_sends(
        ) -> None:
    """CodeRabbit: `note` is always returned, so the contract must say so.

    It is the field that tells an operator no restart is needed -- the
    correction #66 made -- so a generated client that drops it as optional
    loses the answer to the question people actually ask after rotating.
    """
    from unittest.mock import MagicMock

    from arena.public.openapi import build_openapi_spec

    schema = (build_openapi_spec(MagicMock())["paths"]["/v1/token/regenerate"]
              ["post"]["responses"]["200"]["content"]["application/json"]
              ["schema"])

    assert "note" in schema["properties"], schema
    assert schema["properties"]["note"]["type"] == "string", schema
    assert "note" in schema["required"], schema
