"""HTTP surface for the runtime exec-profile switch.

Two endpoints, both authenticated like the rest of the admin surface:

    GET  /v1/admin/profile     what is in force, and what changing costs
    POST /v1/admin/profile     switch it (widening needs consent)

The logic lives in `arena.admin.profile_switch`; this file is wiring and
auditing only. Every outcome is audited -- including refusals, because a
rejected privilege request is exactly as interesting as a granted one.
"""
from __future__ import annotations

from aiohttp import web

from arena.admin import profile_switch as _ps
from arena.app_keys import APP_CFG
from arena.handler_helpers import authed


def make_profile_handlers(ctx):
    """Return the profile handlers keyed by short name."""

    @authed(ctx)
    async def handle_profile_get(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        return ctx.cors_json_response(_ps.describe(cfg))

    @authed(ctx)
    async def handle_profile_post(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        try:
            data = await request.json()
        except Exception as exc:  # noqa: BLE001
            return ctx.cors_json_response(
                {"ok": False, "error": f"invalid json: {exc}"}, status=400)

        target = str(data.get("profile") or "").strip()
        consent = data.get("consent")
        before = cfg.get("profile")

        result = _ps.switch(cfg, target=target,
                            consent=str(consent) if consent else None)

        # Audit everything. A privilege change with no trace is
        # indistinguishable from a compromise, and a refusal is evidence
        # of an attempt.
        ctx.audit({
            "type": "profile.switch",
            "from": before,
            "to": cfg.get("profile"),
            "requested": target,
            "granted": bool(result.get("changed")),
            "consent_supplied": bool(consent),
            "client": request.remote or "local-client",
        })

        if result.get("ok"):
            return ctx.cors_json_response(result)
        # A consent challenge is not an error the caller did wrong; 200
        # with consent_required is the same shape update/apply uses.
        status = 200 if result.get("consent_required") else 400
        return ctx.cors_json_response(result, status=status)

    return {"profile_get": handle_profile_get,
            "profile_post": handle_profile_post}
