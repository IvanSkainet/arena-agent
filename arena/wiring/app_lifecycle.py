"""app factory and lifecycle wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from arena.wiring.env import RuntimeEnv


def build_app_lifecycle(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build make_app, lifecycle runtime and startup/cleanup globals."""
    env = RuntimeEnv(g)
    registry: dict[str, Any] = {}

    def _set_app_ref(app) -> None:
        g["_app_ref"] = app

    def make_app(cfg: dict):
        container = env.build_container(g)
        return env._make_arena_app(
            cfg,
            handlers=container.handlers,
            error_middleware=g["error_middleware"],
            on_startup=g["on_startup"],
            on_cleanup=g["on_cleanup"],
            set_app_ref=_set_app_ref,
        )

    def _get_shutdown_event():
        return g.get("_shutdown_event")

    def _get_mission_schedule_loop():
        return g.get("mission_schedule_loop")

    # v4.22.1 + v4.38.0: autostart bindings, one per transport with
    # a start/stop verb. Each reads its marker + env var on boot,
    # no-op if neither is set. Placed here so the lifecycle module
    # doesn't need to know anything about a specific transport's
    # dependencies.
    def _resolved_port() -> int:
        # Port comes from the runtime config populated at boot; the
        # bridge only listens on one port so this is unambiguous.
        port = 8765
        try:
            cfg_ref = g.get("_app_ref")
            if cfg_ref is not None:
                from arena.app_keys import APP_CFG
                port = int(cfg_ref[APP_CFG].get("port", 8765))
        except Exception:
            pass
        return port

    def _cloudflared_autostart():
        from arena.admin.cloudflared_autostart import run_autostart
        cloudflared_fn = g.get("_cloudflared_funnel_action_runtime")
        subprocess_kwargs_fn = g.get("_subprocess_kwargs")
        root_agent = g.get("ROOT_AGENT")
        if cloudflared_fn is None or subprocess_kwargs_fn is None or root_agent is None:
            return None
        return run_autostart(
            root_agent=root_agent,
            port=_resolved_port(),
            cloudflared_funnel_action_fn=cloudflared_fn,
            subprocess_kwargs_fn=subprocess_kwargs_fn,
        )

    def _ngrok_autostart():
        # v4.38.0: same shape as cloudflared, but native (no
        # ngrok_autostart module). We call the shared unified
        # autostart module + the ngrok_action directly.
        from arena.admin import autostart as _autostart
        from arena.admin.cloudflared_autostart import AutostartOutcome
        import time as _time
        root_agent = g.get("ROOT_AGENT")
        subprocess_kwargs_fn = g.get("_subprocess_kwargs")
        if root_agent is None or subprocess_kwargs_fn is None:
            return None
        if not _autostart.is_enabled("ngrok", root_agent):
            return AutostartOutcome(attempted=False, ok=False, url="",
                                    reason="no marker, env unset",
                                    duration_sec=0.0)
        from arena.admin.ngrok import ngrok_action
        t0 = _time.monotonic()
        try:
            result = ngrok_action("start", _resolved_port(),
                                  root_agent=root_agent,
                                  subprocess_kwargs=subprocess_kwargs_fn)
        except Exception as e:  # noqa: BLE001
            return AutostartOutcome(
                attempted=True, ok=False, url="",
                reason=f"start call raised: {type(e).__name__}: {str(e)[:200]}",
                duration_sec=round(_time.monotonic() - t0, 3),
            )
        ok = bool(result.get("ok"))
        return AutostartOutcome(
            attempted=True, ok=ok,
            url=str(result.get("url", "")),
            reason=("started" if ok else
                    str(result.get("error", "unknown"))[:200]),
            duration_sec=round(_time.monotonic() - t0, 3),
        )

    def _tailscale_autostart():
        # v4.38.0: same shape as cloudflared / ngrok. tailscale
        # doesn't use subprocess_kwargs but takes the same
        # (action, port) signature via arena.admin.runtime.
        from arena.admin import autostart as _autostart
        from arena.admin.cloudflared_autostart import AutostartOutcome
        import time as _time
        root_agent = g.get("ROOT_AGENT")
        if root_agent is None:
            return None
        if not _autostart.is_enabled("tailscale", root_agent):
            return AutostartOutcome(attempted=False, ok=False, url="",
                                    reason="no marker, env unset",
                                    duration_sec=0.0)
        from arena.admin.runtime import tailscale_funnel_action
        t0 = _time.monotonic()
        try:
            result = tailscale_funnel_action("start", _resolved_port())
        except Exception as e:  # noqa: BLE001
            return AutostartOutcome(
                attempted=True, ok=False, url="",
                reason=f"start call raised: {type(e).__name__}: {str(e)[:200]}",
                duration_sec=round(_time.monotonic() - t0, 3),
            )
        ok = bool(result.get("ok"))
        return AutostartOutcome(
            attempted=True, ok=ok,
            url=str(result.get("public_url") or result.get("url", "")),
            reason=("started" if ok else
                    str(result.get("error", "unknown"))[:200]),
            duration_sec=round(_time.monotonic() - t0, 3),
        )

    lifecycle_ctx = env.LifecycleContext(
        executor=env._EXECUTOR,
        slow_executor=env._SLOW_EXECUTOR,
        init_memory_db=lambda: g["init_memory_db"](),
        task_runner_loop=g["task_runner_loop"],
        log_cleanup_loop=g["_log_cleanup_loop"],
        file_watch_loop=g["file_watch_loop"],
        get_mission_schedule_loop=_get_mission_schedule_loop,
        start_watchdog=env._start_watchdog,
        stop_watchdog=env._stop_watchdog,
        stop_cdp_watcher=env._stop_cdp_watcher,
        cdp_state=env._cdp_state,
        stop_grpc_server=env.stop_grpc_server,
        stop_cluster_heartbeat=env.stop_cluster_heartbeat,
        get_shutdown_event=_get_shutdown_event,
        version=env.VERSION,
        log_info=env.log.info,
        log_debug=env.log.debug,
        cloudflared_autostart=_cloudflared_autostart,
        ngrok_autostart=_ngrok_autostart,
        tailscale_autostart=_tailscale_autostart,
    )
    lifecycle_runtime = env.make_lifecycle(lifecycle_ctx)
    registry.update({
        "_set_app_ref": _set_app_ref,
        "make_app": make_app,
        "_get_shutdown_event": _get_shutdown_event,
        "_get_mission_schedule_loop": _get_mission_schedule_loop,
        "_lifecycle_ctx": lifecycle_ctx,
        "_lifecycle_runtime": lifecycle_runtime,
        "on_startup": lifecycle_runtime.on_startup,
        "on_cleanup": lifecycle_runtime.on_cleanup,
        "_signal_handler": lifecycle_runtime.signal_handler,
    })
    return registry


__all__ = ["build_app_lifecycle"]
