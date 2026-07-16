"""Handlers for token regeneration and tunnel/funnel administration.

v3.93.0: Migrated to `@authed` decorator + `err_json` helper from
`arena/handler_helpers.py`. Removes ~110 lines of auth/record/try boilerplate
without changing any wire behaviour — same responses, same status codes,
same audit trail.
"""
from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.admin.runtime import (
    cloudflared_funnel_action,
    sys_funnel_status,
    tailscale_funnel_action,
    token_regenerate,
    zerotier_status,
    zerotier_network_action,
    zerotier_peers,
)
from arena.admin.tunnels import (
    tunnels_status,
    tunnels_active,
    tunnels_start,
    tunnels_stop,
    tunnels_probe,
)
from arena.handler_context import AdminHandlerContext
from arena.handler_helpers import authed


@dataclass(frozen=True)
class AdminHandlers:
    sys_funnel: object
    token_regenerate: object
    tailscale_funnel: object
    cloudflared_tunnel: object
    # v4.33.0: ngrok as fourth transport (POST /v1/ngrok/tunnel/{action}).
    ngrok_tunnel: object
    zerotier_status: object
    zerotier_network: object
    # v4.4.0: per-peer classification (direct / relay / root / tunneled).
    zerotier_peers: object
    tunnels_status: object
    tunnels_active: object
    tunnels_start: object
    tunnels_stop: object
    # v4.1.0: reachability probe for the active transport.
    tunnels_probe: object
    # v4.14.0: manual reset of the circuit-breaker records.
    tunnels_probe_reset: object
    # v4.1.0: agent-facing "which URL should I use" endpoint.
    agent_config: object
    # v3.85.0: cross-platform auto-update.
    update_status: object
    update_check: object
    update_apply: object
    update_restart: object
    # v3.96.0: ZeroTier Central management surface.
    zt_central_status: object
    zt_central_networks_list: object
    zt_central_networks_create: object
    zt_central_network_get: object
    zt_central_network_delete: object
    zt_central_members_list: object
    zt_central_member_update: object
    zt_central_member_delete: object
    # v4.19.0: agent-driven change proposals.
    proposal_submit: object
    proposal_status: object
    proposal_list: object


def make_admin_handlers(ctx: AdminHandlerContext) -> AdminHandlers:
    @authed(ctx)
    async def handle_v1_sys_funnel(request: web.Request) -> web.Response:
        """GET /v1/sys/funnel — Tailscale Funnel status."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(sys_funnel_status, subprocess_kwargs=ctx.subprocess_kwargs),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_token_regenerate(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        target = str(cfg.get("token_file") or "")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            lambda: token_regenerate(target, default_token_file=ctx.default_token_file),
        )
        if result.get("ok") and result.get("token"):
            cfg["token"] = result["token"]
        ctx.audit({"type": "token_regenerated", "files": result.get("written_to", [])})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tailscale_funnel(request: web.Request) -> web.Response:
        action = request.match_info.get("action", "status")
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, tailscale_funnel_action, action, port)
        ctx.audit({"type": "tailscale_funnel", "action": action, "ok": result.get("ok")})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_cloudflared_tunnel(request: web.Request) -> web.Response:
        action = request.match_info.get("action", "status")
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            lambda: cloudflared_funnel_action(
                action,
                port,
                root_agent=ctx.root_agent,
                subprocess_kwargs=ctx.subprocess_kwargs,
            ),
        )
        # v4.22.1: persist the autostart intent so a bridge restart
        # re-establishes the tunnel automatically. Only successful
        # start/stop calls update the marker so a failed start
        # doesn't leave a stale intent behind.
        if action == "start" and result.get("ok"):
            try:
                from arena.admin.cloudflared_autostart import mark_autostart
                mark_autostart(ctx.root_agent, port=port)
                result["autostart_marked"] = True
            except Exception:
                # Marker is best-effort — never block a successful
                # start on a filesystem hiccup.
                result["autostart_marked"] = False
        elif action == "stop" and result.get("ok"):
            try:
                from arena.admin.cloudflared_autostart import unmark_autostart
                result["autostart_cleared"] = unmark_autostart(ctx.root_agent)
            except Exception:
                result["autostart_cleared"] = False
        ctx.audit({"type": "cloudflared_tunnel", "action": action, "ok": result.get("ok")})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_ngrok_tunnel(request: web.Request) -> web.Response:
        """POST /v1/ngrok/tunnel/{action} -- ngrok as the fourth
        transport (v4.33.0). Same start / stop / status shape as
        cloudflared so the dashboard can treat them as siblings.

        Autostart persistence is intentionally not wired in this
        release; adding a sibling ``.ngrok_autostart`` marker
        follows in a subsequent release, once we've observed
        ngrok's behaviour across a few live restarts (same
        cadence cloudflared followed: wire first, autostart
        second)."""
        # Guard: if ngrok_status_sync isn't wired (older ctx or a
        # test context predating v4.33.0), fall back to a local
        # import so the endpoint still works. Bridge boot never
        # blocks on ngrok even when unused.
        action = request.match_info.get("action", "status")
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        from arena.admin.ngrok import ngrok_action
        result = await loop.run_in_executor(
            ctx.executor,
            lambda: ngrok_action(
                action,
                port,
                root_agent=ctx.root_agent,
                subprocess_kwargs=ctx.subprocess_kwargs,
            ),
        )
        ctx.audit({"type": "ngrok_tunnel", "action": action, "ok": result.get("ok")})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_zerotier_status(request: web.Request) -> web.Response:
        """GET /v1/zerotier/status — ZeroTier status."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(zerotier_status, subprocess_kwargs=ctx.subprocess_kwargs),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_zerotier_network(request: web.Request) -> web.Response:
        """POST/GET /v1/zerotier/network/{action} — ZeroTier network actions.

        Accepts network_id from any of: URL query string, JSON body, or
        application/x-www-form-urlencoded body — so both curl and browsers
        (Dashboard) can drive it without extra ceremony.
        """
        action = request.match_info.get("action", "status")

        # 1) Always allow ?network_id=... regardless of method.
        network_id = request.query.get("network_id")

        # 2) POST body: JSON or form-urlencoded.
        if request.method == "POST" and not network_id:
            ctype = (request.headers.get("Content-Type") or "").lower()
            try:
                if "application/json" in ctype:
                    body = await request.json()
                    network_id = body.get("network_id")
                elif "application/x-www-form-urlencoded" in ctype:
                    form = await request.post()
                    network_id = form.get("network_id")
                else:
                    # Best-effort: try JSON first, fall back to raw text.
                    raw = await request.text()
                    if raw.strip().startswith("{"):
                        import json as _json
                        try:
                            network_id = _json.loads(raw).get("network_id")
                        except Exception:
                            pass
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            zerotier_network_action,
            action,
            network_id,
        )
        ctx.audit({"type": "zerotier_network", "action": action, "ok": result.get("ok")})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_zerotier_peers(request: web.Request) -> web.Response:
        """GET /v1/zerotier/peers -- per-peer classification.

        Returns each ZeroTier peer with a ``path_kind`` label
        (``direct`` / ``relay`` / ``root`` / ``tunneled`` / ``none``)
        so agents and the Dashboard can tell at a glance whether the
        overlay is running on real P2P UDP paths or being relayed
        through a PLANET root. Cross-platform: uses the ZeroTier
        local HTTP API when the authtoken is readable, otherwise
        falls back to ``zerotier-cli -j peers`` (honouring the
        optional ``zerotier-cli-wrapper`` sudo helper on Linux).
        """
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, zerotier_peers)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_status(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_status,
                port=port,
                sys_funnel_status_sync=ctx.sys_funnel_status_sync,
                cloudflared_status_sync=ctx.cloudflared_status_sync,
                zerotier_status_sync=ctx.zerotier_status_sync,
                # v4.33.0: opt-in ngrok context; getattr keeps back-
                # compat with older ctx snapshots from tests.
                ngrok_status_sync=getattr(ctx, "ngrok_status_sync", None),
            ),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_active(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_active,
                port=port,
                sys_funnel_status_sync=ctx.sys_funnel_status_sync,
                cloudflared_status_sync=ctx.cloudflared_status_sync,
                zerotier_status_sync=ctx.zerotier_status_sync,
                ngrok_status_sync=getattr(ctx, "ngrok_status_sync", None),
            ),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_start(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_start,
                port=port,
                tailscale_funnel_action_sync=ctx.tailscale_funnel_action_sync,
                cloudflared_funnel_action_sync=ctx.cloudflared_funnel_action_sync,
                sys_funnel_status_sync=ctx.sys_funnel_status_sync,
                cloudflared_status_sync=ctx.cloudflared_status_sync,
                zerotier_status_sync=ctx.zerotier_status_sync,
            ),
        )
        ctx.audit({"type": "tunnels_start", "active": (result.get("active") or {}).get("provider")})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_stop(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_stop,
                port=port,
                tailscale_funnel_action_sync=ctx.tailscale_funnel_action_sync,
                cloudflared_funnel_action_sync=ctx.cloudflared_funnel_action_sync,
            ),
        )
        ctx.audit({"type": "tunnels_stop"})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_probe(request: web.Request) -> web.Response:
        """GET /v1/tunnels/probe — TCP-connect reachability check for
        every transport's advertised public URL.

        v4.1.0: this is the endpoint agents should call to decide which
        URL to actually dial. ``/v1/tunnels/active`` trusts the
        provider's self-report; ``/v1/tunnels/probe`` proves the
        provider is really reachable end-to-end.
        """
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        # Query params: ?timeout=SECONDS overrides the default 1.5s
        # per-provider TCP timeout (agents can dial it down when
        # polling frequently, or up on high-latency links).
        try:
            timeout = float(request.query.get("timeout", "1.5"))
        except (TypeError, ValueError):
            timeout = 1.5
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_probe,
                port=port,
                timeout=timeout,
                sys_funnel_status_sync=ctx.sys_funnel_status_sync,
                cloudflared_status_sync=ctx.cloudflared_status_sync,
                zerotier_status_sync=ctx.zerotier_status_sync,
                ngrok_status_sync=getattr(ctx, "ngrok_status_sync", None),
            ),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_probe_reset(request: web.Request) -> web.Response:
        """POST /v1/tunnels/probe/reset -- clear one or all circuit
        breaker records so a provider can be re-probed immediately
        instead of waiting for the 60s cooldown to elapse (v4.14.0).

        Body (JSON, optional):
            {"key": "cloudflared|foo.trycloudflare.com:443"}

        Empty / missing body resets every record. Returns the
        pre-reset snapshot so the caller can see what got cleared
        without a second /v1/tunnels/probe round-trip.

        v4.8.0 CHANGELOG left this as follow-up work: the breaker
        used to have exactly two escape hatches -- wait 60s or
        ``systemctl restart arena-bridge``. Neither felt like a
        first-class ops tool. Now there's a proper endpoint the
        Dashboard's Network Status card can drive from a button.
        """
        from arena.admin.tunnels_breaker import get_default_breaker
        key = None
        try:
            data = await request.json()
            if isinstance(data, dict):
                raw = data.get("key")
                if isinstance(raw, str) and raw.strip():
                    key = raw.strip()
        except Exception:
            # Empty body / non-JSON -- reset all.
            pass

        breaker = get_default_breaker()
        before = breaker.snapshot()
        if key is not None:
            breaker.reset(key)
        else:
            breaker.reset()

        ctx.audit({
            "type": "tunnels_breaker_reset",
            "key": key or "all",
            "keys_cleared": (1 if key else len(before)),
            "client": request.remote or "127.0.0.1",
        })
        return ctx.cors_json_response({
            "ok": True,
            "reset": key or "all",
            "keys_cleared": (1 if key else len(before)),
            "breaker_before": before,
            "breaker_after": breaker.snapshot(),
        })

    @authed(ctx)
    async def handle_v1_agent_config(request: web.Request) -> web.Response:
        """GET /v1/agent/config — return every transport URL that is
        currently reachable, in priority order, so an agent can pick
        one and connect. v4.1.0.

        Response shape::

            {
              "ok": true,
              "version": "4.1.0",
              "priority": ["tailscale", "zerotier", "cloudflared"],
              "urls": [
                {"provider": "tailscale", "url": "https://…", "kind": "https"},
                {"provider": "zerotier",  "url": "http://10.57.152.120:8765", "kind": "http-lan"}
              ],
              "primary": {"provider": "tailscale", "url": "https://…"},
              "hint": "Bearer token still required on every call."
            }

        The intent: an agent (or its bootstrap script) calls this once
        and gets an ordered list of URLs it can dial. Same auth as
        every other admin endpoint so the token doesn't leak.
        """
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        try:
            timeout = float(request.query.get("timeout", "1.5"))
        except (TypeError, ValueError):
            timeout = 1.5
        loop = asyncio.get_running_loop()
        probe = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_probe,
                port=port,
                timeout=timeout,
                sys_funnel_status_sync=ctx.sys_funnel_status_sync,
                cloudflared_status_sync=ctx.cloudflared_status_sync,
                zerotier_status_sync=ctx.zerotier_status_sync,
                ngrok_status_sync=getattr(ctx, "ngrok_status_sync", None),
            ),
        )
        # Distill probe output down to a compact url-list for the agent.
        urls = []
        for p in probe.get("probes", []):
            if not p.get("reachable"):
                continue
            urls.append({
                "provider": p.get("provider"),
                "url": p.get("public_url"),
                "kind": p.get("public_kind") or (
                    "https" if str(p.get("public_url", "")).startswith("https://")
                    else "http-lan"),
            })
        # v4.16.0: distill the breaker snapshot v4.8.0 embedded in
        # probe response into a compact per-provider summary the
        # agent can act on without a second round-trip.
        from arena.admin.tunnels_breaker import summarize_snapshot
        breaker_summary = summarize_snapshot(probe.get("breaker") or {})
        deprio = set(breaker_summary["open"])
        # v4.16.0: rebuild priority + reorder urls so any provider
        # with an open breaker sinks to the tail. Order among
        # deprio'd providers preserved from the original priority
        # so a partial recovery still surfaces one usable URL up
        # top. Non-deprio'd providers keep their original priority
        # ordering exactly.
        original_priority = list(probe.get("priority") or ())
        if deprio and original_priority:
            keep = [p for p in original_priority if p not in deprio]
            sink = [p for p in original_priority if p in deprio]
            effective_priority = keep + sink
        else:
            effective_priority = original_priority
        if deprio and urls:
            urls.sort(key=lambda u: (
                1 if u.get("provider") in deprio else 0,
                effective_priority.index(u.get("provider"))
                    if u.get("provider") in effective_priority
                    else len(effective_priority),
            ))
        # Recompute primary AFTER the reorder so it matches urls[0].
        primary = None
        if urls:
            primary = {"provider": urls[0].get("provider"),
                       "public_url": urls[0].get("url")}
        else:
            primary = probe.get("active")
        # v4.1.0: constants.VERSION is authoritative.
        from arena.constants import VERSION
        return ctx.cors_json_response({
            "ok": True,
            "version": VERSION,
            "priority": effective_priority or probe.get("priority"),
            "priority_original": original_priority if deprio else None,
            "urls": urls,
            "primary": primary,
            "reachable_count": probe.get("reachable_count", len(urls)),
            # v4.16.0: agent-facing summary of the circuit breaker.
            # Empty (no records) on a fresh bridge; grows as probes
            # accumulate failures. See summarize_snapshot() for the
            # shape.
            "breaker_summary": breaker_summary,
            "deprioritized": sorted(deprio) if deprio else [],
            "hint": (
                "Bearer token still required on every call. If no URL is "
                "reachable, check firewall (bridge listens on all "
                "interfaces via --bind auto / ARENA_AUTO_BIND=1 when a "
                "Tailscale or ZeroTier interface is detected)."
            ),
        })

    # v3.85.0: auto-update handlers live in a sibling module to keep
    # this file small.
    from arena.admin.handlers_update import make_update_handlers
    _upd = make_update_handlers(ctx)

    # v3.96.0: ZeroTier Central management handlers live in a
    # sibling module too — same reason.
    from arena.admin.zerotier_central_handlers import make_zerotier_central_handlers
    _ztc = make_zerotier_central_handlers(ctx)

    # v4.19.0: agent proposal handlers. Repo root is derived
    # from BRIDGE_DIR (constants.py). Kept in a sibling module
    # because the whole apply+test pipeline is ~250 lines.
    from arena.admin.handlers_proposal import make_proposal_handlers
    from arena.constants import BRIDGE_DIR
    _prop = make_proposal_handlers(ctx, BRIDGE_DIR)

    return AdminHandlers(
        sys_funnel=handle_v1_sys_funnel,
        token_regenerate=handle_v1_token_regenerate,
        tailscale_funnel=handle_v1_tailscale_funnel,
        cloudflared_tunnel=handle_v1_cloudflared_tunnel,
        ngrok_tunnel=handle_v1_ngrok_tunnel,
        zerotier_status=handle_v1_zerotier_status,
        zerotier_network=handle_v1_zerotier_network,
        zerotier_peers=handle_v1_zerotier_peers,
        tunnels_status=handle_v1_tunnels_status,
        tunnels_active=handle_v1_tunnels_active,
        tunnels_start=handle_v1_tunnels_start,
        tunnels_stop=handle_v1_tunnels_stop,
        tunnels_probe=handle_v1_tunnels_probe,
        tunnels_probe_reset=handle_v1_tunnels_probe_reset,
        agent_config=handle_v1_agent_config,
        update_status=_upd["update_status"],
        update_check=_upd["update_check"],
        update_apply=_upd["update_apply"],
        update_restart=_upd["update_restart"],
        zt_central_status=_ztc.status,
        zt_central_networks_list=_ztc.networks_list,
        zt_central_networks_create=_ztc.networks_create,
        zt_central_network_get=_ztc.network_get,
        zt_central_network_delete=_ztc.network_delete,
        zt_central_members_list=_ztc.members_list,
        zt_central_member_update=_ztc.member_update,
        zt_central_member_delete=_ztc.member_delete,
        # v4.19.0: agent-driven change proposals.
        proposal_submit=_prop["proposal_submit"],
        proposal_status=_prop["proposal_status"],
        proposal_list=_prop["proposal_list"],
    )
