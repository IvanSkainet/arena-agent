"""Legacy app factory and lifecycle wiring."""
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

    lifecycle_ctx = env.LifecycleContext(
        executor=env._EXECUTOR,
        slow_executor=env._SLOW_EXECUTOR,
        init_memory_db=lambda: g["init_memory_db"](),
        task_runner_loop=g["task_runner_loop"],
        log_cleanup_loop=g["_log_cleanup_loop"],
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
    )
    lifecycle_runtime = env.make_lifecycle(lifecycle_ctx)
    registry.update({
        "_set_app_ref": _set_app_ref,
        "make_app": make_app,
        "_get_shutdown_event": _get_shutdown_event,
        "_lifecycle_ctx": lifecycle_ctx,
        "_lifecycle_runtime": lifecycle_runtime,
        "on_startup": lifecycle_runtime.on_startup,
        "on_cleanup": lifecycle_runtime.on_cleanup,
        "_signal_handler": lifecycle_runtime.signal_handler,
    })
    return registry


__all__ = ["build_app_lifecycle"]
