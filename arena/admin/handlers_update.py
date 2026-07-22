"""aiohttp handlers for the auto-update surface (v3.85.0).

Split out of `arena/admin/handlers.py` to keep that module small.
All four handlers gate on `ctx.require_auth` like the rest of the
admin surface and audit their effects.

v3.93.0: Migrated to `@authed` + `err_json` from arena.handler_helpers,
replacing repetitive auth/record/try preludes.
"""
from __future__ import annotations

import asyncio
import functools

from aiohttp import web

from arena.admin import auto_update as _upd
from arena.handler_helpers import authed, err_json


async def _run(ctx, fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(ctx.executor, functools.partial(fn, *args, **kwargs))


def make_update_handlers(ctx):
    """Return the 4 update handler coroutines keyed by short name."""

    @authed(ctx)
    async def handle_update_status(request: web.Request) -> web.Response:
        """GET /v1/admin/update/status -- cached view of current version
        plus repository + install-root diagnostics. Does NOT hit
        GitHub -- use /v1/admin/update/check for that."""
        from arena.constants import VERSION
        import platform
        sysname = platform.system().lower()
        # v3.86.3: show "GNU/Linux" instead of just "Linux" for
        # Linux hosts; keep the machine-readable `platform` field as
        # `linux` because downstream code branches on it, but expose
        # a `platform_display` for the UI. Same principle for
        # macOS ("darwin" -> "macOS").
        display_map = {
            "linux":   "GNU/Linux",
            "darwin":  "macOS",
            "windows": "Windows",
        }
        payload = {
            "ok": True,
            "current": VERSION,
            "repo": _upd._repo(),
            "install_root": str(_upd._install_root()),
            "platform": sysname,
            "platform_display": display_map.get(sysname, sysname.capitalize()),
            "restart_hint": (
                "Windows: service supervisor (nssm / Windows service) "
                "will relaunch after apply."
                if sysname == "windows"
                else "systemd / launchd will restart automatically on exit."
            ),
        }
        # v4.50.0: expose token source so the UI knows whether to
        # show the "add token" banner or the "token active" chip.
        try:
            from arena.admin.update_github import github_token_source
            payload["github_token_source"] = github_token_source()
        except Exception:
            payload["github_token_source"] = "unknown"
        return ctx.cors_json_response(payload)

    @authed(ctx)
    async def handle_update_check(request: web.Request) -> web.Response:
        """POST /v1/admin/update/check -- talk to GitHub, return the
        latest release + whether we need updating. Body is optional
        `{repo?: str}` to override the default repo (test-friendly)."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if isinstance(body, dict) and body.get("repo"):
            import os
            os.environ["ARENA_UPDATE_REPO"] = str(body["repo"]).strip()
        res = await _run(ctx, _upd.check_updates)
        ctx.audit({
            "type": "admin.update.check",
            "current": res.get("current"),
            "latest": res.get("latest"),
            "needs_update": res.get("needs_update"),
            "ok": res.get("ok"),
        })
        return ctx.cors_json_response(res)

    @authed(ctx)
    async def handle_update_apply(request: web.Request) -> web.Response:
        """POST /v1/admin/update/apply
        Body: {tag, asset_url, asset_name, expected_sha256, consent, restart?}
        Consent token comes from `consent_token(tag, sha256)`; a
        first call without consent returns the required token so the
        Dashboard can echo it back on the second call.
        """
        try:
            body = await request.json()
        except Exception:
            return err_json(ctx, "JSON body required", status=400)
        tag = str(body.get("tag") or "").strip()
        asset_url = str(body.get("asset_url") or "").strip()
        asset_name = str(body.get("asset_name") or "").strip()
        expected = str(body.get("expected_sha256") or "").strip()
        consent = str(body.get("consent") or "").strip()
        restart = bool(body.get("restart", True))
        # v4.50.2: opt-in "install without SHA-256 verification".
        # Only honoured when expected is empty; if the caller sends
        # BOTH a real digest AND accept_no_verification we still
        # verify -- explicit is better than implicit.
        accept_no_verification = bool(body.get("accept_no_verification", False))

        if not (tag and asset_url and asset_name):
            return err_json(
                ctx,
                "tag, asset_url, asset_name all required",
                status=400,
            )
        if not expected and not accept_no_verification:
            return err_json(
                ctx,
                "expected_sha256 required (or set accept_no_verification=true)",
                status=400,
            )

        # First call without consent: return the token so the caller
        # can echo it back for the actual install. Consent shape
        # depends on whether we are on the verified or unverified
        # path so a stored consent from one path cannot be replayed
        # to trigger the other.
        digest_for_consent = (
            expected.split(":", 1)[-1].strip().lower() if expected else "UNVERIFIED"
        )
        required_consent = _upd.consent_token(tag=tag, sha256=digest_for_consent)
        if not consent:
            return ctx.cors_json_response({
                "ok": False,
                "consent_required": True,
                "required_consent": required_consent,
                "tag": tag,
                "asset_name": asset_name,
                "sha256": expected or None,
                "verification": "unverified" if not expected else "sha256",
                "hint": "Resend the same request with consent=<required_consent>.",
            })

        res = await _run(
            ctx, _upd.apply_update,
            asset_url=asset_url, asset_name=asset_name, tag=tag,
            expected_sha256=expected or None, consent=consent, restart=restart,
            accept_no_verification=accept_no_verification,
        )
        ctx.audit({
            "type": "admin.update.apply",
            "tag": tag,
            "sha256": expected or "UNVERIFIED",
            "verification": (res.get("verification")
                             if isinstance(res, dict) else None),
            "downloaded_sha256": (res.get("downloaded_sha256")
                                  if isinstance(res, dict) else None),
            "swapped": (res.get("swapped") if isinstance(res, dict) else None),
            "ok": res.get("ok") if isinstance(res, dict) else False,
        })
        # If apply succeeded AND caller wanted restart, schedule an
        # in-process exit / execv AFTER we return the HTTP response.
        #
        # v4.60.13: pre-v4.60.13 this branch was gated on
        # ``res.get("platform") != "windows"`` because before v4.60.4
        # ``restart_process`` on Windows was a no-op returning
        # ``{"restart": "pending"}``. v4.60.4 fixed ``restart_process``
        # to actually schedule ``os._exit(0)`` on a background thread,
        # but this gate was never removed -- so the Dashboard "Install"
        # button reported success but the bridge kept running, the
        # mover script waited for our PID to disappear forever, and
        # the version never changed. Ivan hit this on every field
        # attempt at auto-update in the v4.60.9 -> v4.60.12 series.
        # Remove the gate: rely on ``restart_process`` doing the right
        # thing on every platform.
        #
        # v4.60.14: also emit an ``admin.update.apply.restart_scheduled``
        # audit event immediately BEFORE calling restart_process, so we
        # can prove from the field audit trail that the handler reached
        # this point. Missing event => handler bailed earlier (e.g.
        # apply_update returned ok=False). Present event => bridge is
        # about to exit and the mover should take over.
        if isinstance(res, dict) and res.get("ok") and restart:
            ctx.audit({
                "type": "admin.update.apply.restart_scheduled",
                "tag": tag,
                "platform": res.get("platform"),
                "delay_sec": 1.0,
            })
            _upd.restart_process(delay_sec=1.0)
            res["restart"] = "scheduled"
        return ctx.cors_json_response(res)

    @authed(ctx)
    async def handle_update_restart(request: web.Request) -> web.Response:
        """POST /v1/admin/update/restart -- manual restart trigger.
        Used for testing and for the Windows "installer done" callback."""
        res = await _run(ctx, _upd.restart_process)
        ctx.audit({
            "type": "admin.update.restart",
            "ok": res.get("ok"),
            "restart": res.get("restart"),
        })
        return ctx.cors_json_response(res)

    @authed(ctx)
    async def handle_update_token_set(request: web.Request) -> web.Response:
        """POST /v1/admin/update/token-set -- accept a JSON body
        {token: '...'} and persist it to <install_root>/.github_token
        so subsequent auto-update calls can use it without an env var.
        v4.50.0: unblocks Windows operators who cannot easily edit
        the service's environment. Master-token authed like every
        other admin surface. The token itself is never logged --
        audit records only the resolution source."""
        from arena.admin.update_github import (
            save_github_token, github_token_source,
        )
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = str((body or {}).get("token", ""))
        res = await _run(ctx, save_github_token, token)
        ctx.audit({
            "type": "admin.update.token_set",
            "ok": res.get("ok"),
            "source": github_token_source(),
        })
        return ctx.cors_json_response(res)

    @authed(ctx)
    async def handle_update_token_clear(request: web.Request) -> web.Response:
        """POST /v1/admin/update/token-clear -- remove the
        UI-configured token file. Does NOT touch env vars."""
        from arena.admin.update_github import (
            clear_github_token, github_token_source,
        )
        res = await _run(ctx, clear_github_token)
        ctx.audit({
            "type": "admin.update.token_clear",
            "ok": res.get("ok"),
            "removed": res.get("removed"),
            "source": github_token_source(),
        })
        return ctx.cors_json_response(res)

    return {
        "update_status":       handle_update_status,
        "update_check":        handle_update_check,
        "update_apply":        handle_update_apply,
        "update_restart":      handle_update_restart,
        "update_token_set":    handle_update_token_set,
        "update_token_clear":  handle_update_token_clear,
    }
