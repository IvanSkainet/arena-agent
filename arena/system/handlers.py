"""Simple system/version/status/config handlers."""
from __future__ import annotations

import asyncio
import logging
import platform
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.app_keys import APP_CFG
from arena.handler_context import SystemHandlerContext
from arena.handler_helpers import authed

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemHandlers:
    version: Callable[..., Any]
    info: Callable[..., Any]
    status: Callable[..., Any]
    config: Callable[..., Any]
    doctor: Callable[..., Any]
    sysinfo: Callable[..., Any]
    beep: Callable[..., Any]
    notify: Callable[..., Any]
    autonomy_posture_get: Callable[..., Any]
    autonomy_posture_set: Callable[..., Any]


def make_system_handlers(ctx: SystemHandlerContext) -> SystemHandlers:
    async def deployment_status(*, public: bool) -> dict[str, Any]:
        from arena.admin.auto_update import _install_root
        from arena.admin.deployment_provenance import (
            ProvenanceError,
            read_deployed_provenance,
        )

        loop = asyncio.get_running_loop()
        try:
            deployment = await loop.run_in_executor(
                ctx.executor, read_deployed_provenance, _install_root()
            )
        except ProvenanceError as exc:
            return {
                "deploymentModel": "archive",
                "authenticated": False,
                "reason": f"invalid deployed provenance: {exc}",
            }
        if deployment is None:
            return {
                "deploymentModel": "unknown",
                "authenticated": False,
                "reason": "DEPLOYED_PROVENANCE.json is absent",
            }
        if not public:
            return deployment
        return {
            key: deployment[key]
            for key in (
                "deploymentModel", "releaseTag", "installedAt", "authenticated",
            )
        }

    async def handle_v1_version(request: web.Request) -> web.Response:
        try:
            ctx.record_request()
            # v4.169.14: `loopback_only` is published here, on the one
            # unauthenticated endpoint, because the Android app has no
            # way to hold the token -- it lives inside Termux's private
            # tree, which another app may not read. Whether a socket
            # accepts non-local connections is not a secret: anyone who
            # can ask this question can already reach the port. The
            # addresses themselves stay behind /v1/access.
            # Read the bind from the live app config, not from ctx: the
            # system context has no bind field, so getattr would default
            # to "" and this would report loopback_only on every bridge
            # in the world -- a detector that always says the same thing
            # is the empty-scan failure again.
            from arena.app_keys import APP_CFG
            from arena.mobile.access_info import LOOPBACK_BINDS
            from arena.mobile.exposure_cache import exposure_snapshot
            cfg = request.app[APP_CFG]
            bind = str(cfg.get("bind", "") or "")
            loopback_only = bind in LOOPBACK_BINDS
            # A loopback bind blocks direct LAN access; it does not block a
            # tunnel agent, which runs on this host and dials loopback
            # itself. With a Tailscale Funnel up, this endpoint answered
            # `loopback_only: true` to requests arriving *through* that
            # funnel, and the Android screen told the operator "Direct
            # access from other machines: no" about a bridge on the public
            # internet (#54).
            #
            # The memo is filled by the authenticated paths that already
            # probe the providers; this endpoint is unauthenticated, so it
            # must never shell out (`tailscale funnel status` is ~20 ms --
            # a denial-of-service lever for anyone who can reach the port).
            # Named `exposed_publicly`, not `reachable_remotely` as in
            # /v1/access: that one is a plain bool, this one is tri-state.
            # null means nobody has looked recently, which is not the same
            # as "nothing is exposed" -- conflating those is the bug being
            # fixed here, and reusing the name with a wider type would set
            # the same trap for the next reader.
            exposure = exposure_snapshot()
            # v4.169.49 (#63): the interpreter patch level and the exact OS
            # build are a vulnerability-matching shortcut -- "Python 3.14.7 on
            # Windows-10-10.0.19044-SP0" names the precise CVE set to try
            # against this host, and it was readable by anyone who could reach
            # the port. They are not needed here: the Android app reads only
            # `version`, `loopback_only` and `exposed_publicly`, and every
            # authenticated caller already gets `python`/`platform` from
            # `common_status()` via /v1/info and /v1/status.
            #
            # So gate the two fingerprinting fields on authentication instead
            # of deleting them: /v1/version stays a working diagnostic for an
            # operator holding the token, while an anonymous caller learns
            # nothing new. `check_auth` reads the credential without refusing
            # the caller (see SystemHandlerContext) -- `require_auth` would
            # 401 the anonymous poller this endpoint exists to serve.
            #
            # `version` itself stays public: /health, /v2/health, /, /metrics
            # and /api-docs all publish it, installers read it before they
            # hold a token, and the Android screen shows it. Truncating it
            # here alone would cost real function and hide nothing.
            authed_caller = False
            probe = getattr(ctx, "check_auth", None)
            if probe is not None:
                try:
                    authed_caller = bool(probe(request))
                except Exception:
                    # An auth probe that blows up must not upgrade the
                    # caller's privileges, and must not 500 a public route.
                    # It must not be silent either: a miswired auth backend
                    # would otherwise just stop serving the gated fields to
                    # operators holding a valid token, with nothing in the
                    # log to explain it.
                    _log.warning(
                        "[/v1/version] auth probe failed; treating caller as "
                        "anonymous", exc_info=True)
                    authed_caller = False
            deployed = await deployment_status(public=not authed_caller)
            payload = {
                "ok": True,
                "version": ctx.version,
                "service": "arena-unified-bridge",
                "loopback_only": loopback_only,
                "exposed_publicly": exposure["exposed"],
                "deployment": deployed,
            }
            if authed_caller:
                payload["python"] = sys.version.split()[0]
                payload["platform"] = ctx.clean_platform_name()
            return ctx.cors_json_response(payload)
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_info(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            payload = ctx.common_status(request.app[APP_CFG])
            payload["deployment"] = await deployment_status(public=False)
            return ctx.cors_json_response(payload)
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_status(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            payload = ctx.common_status(request.app[APP_CFG])
            payload["deployment"] = await deployment_status(public=False)
            return ctx.cors_json_response(payload)
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    @authed(ctx)
    async def handle_v1_config(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        return ctx.cors_json_response({
            "ok": True,
            "service": "arena-unified-bridge",
            "version": ctx.version,
            "host": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "config": {
                "root": str(cfg.get("root", "")),
                "port": cfg.get("port", 8765),
                "profile": cfg.get("profile", "owner-shell"),
                "audit_log": str(cfg.get("audit", "")),
                "max_concurrent": cfg.get("max_concurrent", 3),
                "token_length": len(cfg.get("token", "")) if cfg.get("token") else 0,
                "token_preview": (cfg.get("token", "")[:4] + "..." + cfg.get("token", "")[-4:])
                                 if cfg.get("token") and len(cfg["token"]) > 8 else "***",
            },
            "endpoints_total": len([r for r in request.app.router.routes()]),
        })


    @authed(ctx)
    async def handle_v1_doctor(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.doctor_sync, request.app[APP_CFG]["token"])
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_sysinfo(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.sysinfo_sync, request.app[APP_CFG]["root"])
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_beep(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            data = {}
        beep_type = data.get("type", "success")
        presets = {"success": (800, 300), "warning": (600, 500), "error": (400, 700), "attention": (1000, 200)}
        freq, dur = presets.get(beep_type, (800, 300))
        try:
            freq = int(data.get("frequency", freq))
            dur = int(data.get("duration", dur))
        except Exception:
            freq, dur = presets.get(beep_type, (800, 300))
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.play_beep_sync, beep_type, freq, dur)
        return ctx.cors_json_response(result)
    @authed(ctx)
    async def handle_v1_notify(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            data = {}
        title = str(data.get("title", "Arena Bridge"))
        message = str(data.get("message", ""))
        sound = bool(data.get("sound", True))
        loop = asyncio.get_running_loop()
        res_v = await loop.run_in_executor(ctx.executor, ctx.send_notification_sync, title, message)
        if sound:
            await loop.run_in_executor(ctx.executor, ctx.play_beep_sync, "success", 800, 300)
        return ctx.cors_json_response(res_v)


    @authed(ctx)
    async def handle_v1_autonomy_posture_get(request: web.Request) -> web.Response:
        """GET /v1/autonomy/posture -- the operator's execution posture (cubes)."""
        from arena.autonomy import posture as _ap
        return ctx.cors_json_response(_ap.get_posture())

    @authed(ctx)
    async def handle_v1_autonomy_posture_set(request: web.Request) -> web.Response:
        """POST /v1/autonomy/posture -- set the posture (MASTER TOKEN ONLY).

        The agent must never relax its own fence, so agent tokens are rejected
        here (v4.102.0 invariant). Risky postures require an ack phrase."""
        try:
            is_agent = "agent_id" in request
        except TypeError:
            is_agent = False
        if is_agent:
            return ctx.cors_json_response(
                {"ok": False,
                 "error": "posture is operator-only; use the master token"},
                status=403)
        from arena.autonomy import posture as _ap
        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body or {}
        p = body.get("posture")
        if not isinstance(p, dict):
            p = {k: body[k] for k in _ap.AXES if k in body}
        res = _ap.set_posture(p, ack=body.get("ack"))
        return ctx.cors_json_response(res, status=200 if res.get("ok") else 400)

    return SystemHandlers(
        version=handle_v1_version,
        info=handle_v1_info,
        status=handle_v1_status,
        config=handle_v1_config,
        doctor=handle_v1_doctor,
        sysinfo=handle_v1_sysinfo,
        beep=handle_v1_beep,
        notify=handle_v1_notify,
        autonomy_posture_get=handle_v1_autonomy_posture_get,
        autonomy_posture_set=handle_v1_autonomy_posture_set,
    )
