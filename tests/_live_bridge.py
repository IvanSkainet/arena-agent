"""One in-process bridge, shared by the contract sweeps that need a real one.

#254 and #259 are the same kind of test: send a request a client could
plausibly send, through the real aiohttp stack, and check the answer is not
the server blaming itself. Both need a running app, and the second copy of
the setup is what SonarCloud flagged as duplication on the #259 PR -- fairly:
the teardown has three obligations that are each easy to get wrong twice.

Kept deliberately small. Anything specific to one contract -- which values
count as malformed, what the refusal must say -- belongs in that test module,
not here.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import unified_bridge as ub


def build_app(root: Path, token: str) -> web.Application:
    app = ub.make_app({
        "token": token, "profile": "owner-shell", "root": root,
        "active_exec": 0, "max_concurrent": 3, "audit": "audit",
        "timeout": 60, "max_timeout": 3600, "max_output": 2000000,
        "allow_any_cwd": False, "semaphore": asyncio.Semaphore(1),
    })
    # Lifecycle hooks tear down the shared executor and poison later tests;
    # routing and parsing do not need the background workers.
    app.on_startup.clear()
    app.on_cleanup.clear()
    app.on_shutdown.clear()
    return app


@asynccontextmanager
async def running_client(root: Path, token: str) -> AsyncIterator[TestClient]:
    """A live in-process bridge, torn down whatever happens.

    Three obligations on the way out, all of them easy to forget: close the
    server, restore the logger, and empty the per-IP rate-limit store so the
    next test is not throttled by this one.
    """
    log = logging.getLogger("arena-bridge")
    previous = log.level
    log.setLevel(logging.CRITICAL)  # a regression here logs a traceback
    server = TestServer(build_app(root, token))
    await server.start_server()
    client = TestClient(server)
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()
        await server.close()
        log.setLevel(previous)
        store = getattr(ub, "_rate_limit_store", None)
        if isinstance(store, dict):
            store.clear()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def json_payload(response) -> dict:
    """The response body as a dict, or {} when it is not one.

    A crashing endpoint may answer HTML or nothing at all; a sweep that
    assumed JSON would fail with a decode error instead of reporting the
    status it was actually sent to check.
    """
    if response.content_type != "application/json":
        return {}
    try:
        body = json.loads(await response.text())
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def error_type_of(payload: dict) -> str | None:
    """The leaked Python class name, if the envelope carries one.

    `error_type` has only ever held an implementation detail the caller
    cannot act on. Both contracts assert it is absent.
    """
    return payload.get("error_type")
