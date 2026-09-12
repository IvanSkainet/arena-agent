"""Bearer-token rotation for `POST /v1/token/regenerate` (#211).

Split out of `arena/admin/handlers.py`, which CodeScene flagged for size
once the #211 work landed. The rotation is self-contained -- it is the
only handler that swaps a live credential, and the only one that has to
keep three things in step: the token file, `cfg["token"]`, and the audit
redactor's list of literals to mask.
"""
from __future__ import annotations

import asyncio

from aiohttp import web

from arena.admin.token import token_regenerate
from arena.app_keys import APP_CFG, APP_TOKEN_ROTATION_LOCK
from arena.handler_context import AdminHandlerContext
from arena.observability.redact import (
    register_literal_secret,
    unregister_literal_secret,
)

__all__ = ["rotate_bridge_token"]


def _install_rotated_token(ctx: AdminHandlerContext, cfg: dict, token: str) -> None:
    """Swap the live credential and keep the audit redactor in step.

    v4.170.0 (#132): registering the new value first means there is no
    window in which the fresh token could reach the audit log unredacted;
    the old one stays registered until after, because an in-flight request
    may still be recording it. The old literal is dropped only once the new
    one is protected -- unregistering first would leave a window with
    neither covered, and dropping it after a *failed* registration would
    leave the live credential unredactable for the rest of the process's
    life.
    """
    if register_literal_secret(token, kind="bridge-token"):
        unregister_literal_secret(cfg["token"])
    cfg["token"] = token


async def rotate_bridge_token(ctx: AdminHandlerContext,
                              request: web.Request) -> web.Response:
    """POST /v1/token/regenerate -- rotate the bearer, truthfully.

    #211: a failed rotation used to be returned as 200 with ok=false in the
    body. Every HTTP client, proxy and retry layer treats 2xx as "it
    worked", so a caller that writes the response over its stored
    credential destroys a working token and has nothing valid left to retry
    with -- unrecoverable without physical access to the machine.

    `token_regenerate` reports exactly one failure, an exception from
    writing the token file, and that is this end's fault, so it is a 500.
    The current credential is untouched and still valid; the body said so
    all along, and now the status agrees with it.

    Lifted out of `make_admin_handlers` so the factory does not grow
    another branch (CodeScene) and so the rotation can be exercised without
    building the whole handler table.
    """
    cfg = request.app[APP_CFG]
    # Shielded, and awaited through the shield rather than directly: a
    # client that disconnects mid-rotation cancels this coroutine, and if
    # the lock were released at that point the executor thread would still
    # be writing. Measured on the unshielded code -- cancel request A while
    # its worker runs, let B complete, and A's write lands afterwards:
    # `A-start, req-cancelled, B-done, A-written`, with the token file
    # holding A and `cfg["token"]` holding B (CodeRabbit). The task owns
    # the lock for its whole life, so the next rotation waits for the
    # write it cannot see.
    return await asyncio.shield(
        asyncio.ensure_future(_rotate_under_lock(ctx, request, cfg)))


async def _rotate_under_lock(ctx: AdminHandlerContext, request: web.Request,
                             cfg: dict) -> web.Response:
    """Hold the rotation lock across the write and the in-memory install."""
    async with _rotation_lock_for(request.app):
        return await _rotate_once(ctx, request, cfg)


def _rotation_lock_for(app: web.Application) -> asyncio.Lock:
    """One rotation at a time per bridge.

    #211 (CodeRabbit): the write runs in an eight-worker executor, so two
    authenticated requests overlap freely. Measured on the unlocked code
    with eight concurrent rotations, two runs in six ended with
    `cfg["token"]` holding a different value than the token file -- the
    executor finished A last while B installed itself in memory. That is
    the same disk/memory divergence this PR exists to close, arrived at
    from the other direction: every client is locked out after a restart.

    The lock lives on the application rather than the module so separate
    bridges in one process (the test rig runs several) do not serialise
    against each other.
    """
    lock = app.get(APP_TOKEN_ROTATION_LOCK)
    if lock is None:
        lock = asyncio.Lock()
        app[APP_TOKEN_ROTATION_LOCK] = lock
    return lock


async def _rotate_once(ctx: AdminHandlerContext, request: web.Request,
                       cfg: dict) -> web.Response:
    """The rotation itself, always under `_rotation_lock_for`."""
    target = str(cfg.get("token_file") or "")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        ctx.executor,
        lambda: token_regenerate(target, default_token_file=ctx.default_token_file),
    )
    if result.get("ok") and result.get("token"):
        _install_rotated_token(ctx, cfg, result["token"])
        ctx.audit({"type": "token_regenerated",
                   "files": result.get("written_to", [])})
        return ctx.cors_json_response(result)

    ctx.audit({"type": "token_regenerate_failed",
               "error": str(result.get("error", "")),
               "client": request.remote or "127.0.0.1"})
    return ctx.cors_json_response(result, status=500)
