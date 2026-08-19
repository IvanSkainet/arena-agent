"""HTTP helpers for public-tunnel acknowledgement (T69).

Split out of ``arena/admin/handlers.py`` so the dispatcher does not keep
absorbing policy wiring. The exact-phrase contract lives in
``tunnel_exposure_policy.py``; this module only reads the request, rejects
unacknowledged public starts, attaches Tailscale's public URL after a
successful start, and emits the opened/closed/denied audit events.
"""
from __future__ import annotations

from typing import Any

from aiohttp import web

from arena.admin.tunnel_exposure_policy import (
    PUBLIC_TUNNEL_ACK_HEADER,
    PUBLIC_TUNNEL_PROVIDERS,
    public_start_denial,
)


def normalize_tunnel_action(action: str | None) -> str:
    """Lowercase the verb before the gate, persist, and audit see it.

    Provider implementations already lowercase internally. Without this,
    ``START`` can pass the policy (which lowercases) and then skip
    ``tunnel_public_opened`` / autostart persist, which compare to
    ``\"start\"``.
    """
    return (action or "status").strip().lower()


async def read_public_exposure_ack(request: web.Request) -> str | None:
    """Return the acknowledgement from header or JSON body.

    A non-empty header wins and is fail-closed: a present wrong header is
    not overridden by a valid JSON ``ack``. Query-string values are
    ignored because URLs are routinely logged. GET/HEAD cannot use a body.
    """
    header = request.headers.get(PUBLIC_TUNNEL_ACK_HEADER)
    if isinstance(header, str) and header:
        return header
    if request.method != "POST":
        return None
    try:
        body = await request.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    ack = body.get("ack")
    return ack if isinstance(ack, str) else None


async def reject_unacknowledged_public_start(
    ctx: Any, request: web.Request, *, provider: str, action: str
) -> web.Response | None:
    """Return HTTP 403 when a public start lacks the exact phrase."""
    denial = public_start_denial(
        provider=provider,
        action=action,
        ack=await read_public_exposure_ack(request),
    )
    if denial is None:
        return None
    ctx.record_request(is_error=True, count_request=False)
    ctx.audit({
        "type": "tunnel_public_ack_denied",
        "provider": provider,
        "action": action,
    })
    return ctx.cors_json_response(denial, status=403)


def apply_funnel_status_url(result: dict[str, Any], status: Any) -> None:
    """Copy ``funnel.url`` onto a Tailscale start result when it has none.

    ``tailscale_funnel_action(\"start\")`` returns ok/action/port/stdio and
    does not parse the public URL. The URL lives on
    ``sys_funnel_status()[\"funnel\"][\"url\"]``. Existing ``url`` /
    ``public_url`` values are left alone.
    """
    if result.get("url") or result.get("public_url"):
        return
    if not isinstance(status, dict):
        return
    funnel = status.get("funnel")
    if not isinstance(funnel, dict):
        return
    url = funnel.get("url")
    if isinstance(url, str) and url.strip():
        result["public_url"] = url
        result["url"] = url


def audit_public_transition(
    ctx: Any, *, provider: str, action: str, result: dict[str, Any]
) -> None:
    """Record opened/closed only after a successful public verb.

    ``tunnel_public_closed`` means the stop verb returned ``ok`` — the
    provider is not publicly exposed. An already-down stop is still a
    successful close, not proof that a previously-open funnel existed.
    """
    if provider not in PUBLIC_TUNNEL_PROVIDERS or not result.get("ok"):
        return
    if action == "start":
        ctx.audit({
            "type": "tunnel_public_opened",
            "provider": provider,
            "public_url": result.get("url") or result.get("public_url"),
        })
    elif action == "stop":
        ctx.audit({"type": "tunnel_public_closed", "provider": provider})


def audit_unified_public_start(ctx: Any, result: dict[str, Any]) -> None:
    """Audit unified ``/v1/tunnels/start`` only when a public provider won."""
    active = result.get("active") or {}
    active_provider = active.get("provider")
    if result.get("ok") and active_provider in PUBLIC_TUNNEL_PROVIDERS:
        ctx.audit({
            "type": "tunnel_public_opened",
            "provider": active_provider,
            "public_url": active.get("public_url"),
        })


def audit_unified_public_stop(ctx: Any, result: dict[str, Any]) -> None:
    """Audit closes only for providers actually driven by ``tunnels_stop``.

    The unified stop facade currently stops Tailscale and cloudflared.
    ngrok/bore are not in that log and must not be claimed closed here.
    """
    for entry in result.get("log", []):
        provider = entry.get("provider")
        provider_result = entry.get("result") or {}
        if (
            provider in PUBLIC_TUNNEL_PROVIDERS
            and entry.get("action") == "stop"
            and provider_result.get("ok")
        ):
            ctx.audit({"type": "tunnel_public_closed", "provider": provider})
