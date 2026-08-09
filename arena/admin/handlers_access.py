"""GET /v1/access -- can anything outside this device reach the bridge?

Split out from /v1/self on purpose. /v1/self answers "what am I and what
can I do"; this answers "and where do I live", which is the question the
Android app has to render on a screen with no other tooling behind it.

The phone made the need concrete: after a reboot it dropped off wireless
ADB (Android disables it), so there was no way in from outside to look.
Whatever the app can show has to be sufficient by itself.
"""
from __future__ import annotations

from aiohttp import web

from arena.app_keys import APP_CFG
from arena.handler_helpers import authed
from arena.mobile import access_info


def make_access_handlers(ctx):
    @authed(ctx)
    async def handle_access(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]

        tunnels: dict = {}
        try:
            from arena.admin import tunnels as _tun
            snap = _tun.tunnels_status() or {}
            providers = snap.get("providers")
            if isinstance(providers, dict):
                tunnels = providers
            elif isinstance(providers, list):
                tunnels = {
                    str(p.get("provider", i)): p
                    for i, p in enumerate(providers)
                    if isinstance(p, dict)
                }
        except Exception:
            # A tunnel provider that throws must not take the address
            # readout with it: the LAN answer is still useful, and this
            # endpoint exists precisely for the case where remote access
            # is already broken.
            tunnels = {}

        return ctx.cors_json_response(access_info.describe(
            bind=str(cfg.get("bind", "127.0.0.1") or "127.0.0.1"),
            port=int(cfg.get("port", 8765) or 8765),
            tunnels=tunnels,
        ))

    return {"access": handle_access}
