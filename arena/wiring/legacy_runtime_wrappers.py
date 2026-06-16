"""Legacy runtime wrapper functions extracted from unified_bridge.py."""
from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from arena.wiring.env import RuntimeEnv

from aiohttp import web


def build_runtime_wrappers(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build compatibility helper globals that wrap focused runtime modules."""
    env = RuntimeEnv(g)
    registry: dict[str, Any] = {}

    async def emit_event(event_type: str, data: dict | None = None) -> None:
        return await env._events_emit_event(event_type, data, utc_now_fn=env.utc_now)

    skills_cache_ref: dict[str, Any] = {"obj": None}

    def _get_skills_cache():
        if skills_cache_ref["obj"] is None:
            skills_cache_ref["obj"] = env.SkillsCache(
                skills_dir=g["SKILLS_DIR"],
                scan_fn=g["_skills_list_sync"],
                ttl=5.0,
                hot_reload=True,
            )
        return skills_cache_ref["obj"]

    def _skills_list_sync_with_cache() -> dict:
        """Scan skills with caching and hot-reload support."""
        return _get_skills_cache().list()

    def _skills_cache_reset() -> None:
        """Reset cached skills so the next list call rescans the filesystem."""
        _get_skills_cache().reset()

    req_log_file = env.APP_DIR / "requests.jsonl"
    req_log_max_bytes = 10 * 1024 * 1024
    req_log_backup_count = 3

    def _log_request_response(method: str, path: str, status: int, duration: float, req_id: str, peer: str = "", error: str = "") -> None:
        """Log request/response to requests.jsonl for observability."""
        return env.request_log_response(
            log_file=req_log_file,
            app_dir=env.APP_DIR,
            utc_now_fn=env.utc_now,
            method=method,
            path=path,
            status=status,
            duration=duration,
            req_id=req_id,
            peer=peer,
            error=error,
            lock=env.request_log_lock,
            max_bytes=req_log_max_bytes,
            backup_count=req_log_backup_count,
        )

    def _start_watchdog() -> None:
        env._watchdog_start(
            utc_now_fn=env.utc_now,
            emit_event_fn=emit_event,
            log_info=env.log.info,
            log_warning=env.log.warning,
            log_error=env.log.error,
        )

    def _stop_watchdog() -> None:
        env._watchdog_stop(log_info=env.log.info)

    def _ensure_profiles_dir() -> Path:
        return env._profiles_ensure_profiles_dir()

    def _generate_self_signed_cert() -> tuple[str, str]:
        return env._tls_generate_self_signed_cert(log_info=env.log.info, log_warning=env.log.warning)

    def _get_tailscale_cert() -> tuple[str, str]:
        return env._tls_get_tailscale_cert(log_info=env.log.info)

    def _check_rate_limit_v2(request: web.Request) -> web.Response | None:
        return env.rl_check_rate_limit_v2(
            request,
            check_auth_with_role_fn=g["check_auth_with_role"],
            cors_json_response_fn=env._cors_json_response,
        )

    async def _run_sandboxed(cmd: str, timeout: int = 30, memory_mb: int = 256) -> dict:
        return await env._sandbox_run_sandboxed(
            cmd,
            timeout=timeout,
            memory_mb=memory_mb,
            root_agent=g["ROOT_AGENT"],
            decode_output_fn=env.decode_output,
        )

    def _get_node_id() -> str:
        return env._cluster_get_node_id()

    async def _cluster_heartbeat_loop() -> None:
        await env._cluster_runtime_heartbeat_loop(log_error=env.log.error)

    def _check_rate_limit(request: web.Request) -> web.Response | None:
        return env.rl_check_rate_limit(request, cors_json_response_fn=env._cors_json_response)

    registry.update({
        "emit_event": emit_event,
        "_skills_cache_obj": skills_cache_ref["obj"],
        "_get_skills_cache": _get_skills_cache,
        "_skills_list_sync_with_cache": _skills_list_sync_with_cache,
        "_skills_cache_reset": _skills_cache_reset,
        "_REQ_LOG_FILE": req_log_file,
        "_REQ_LOG_MAX_BYTES": req_log_max_bytes,
        "_REQ_LOG_BACKUP_COUNT": req_log_backup_count,
        "_log_request_response": _log_request_response,
        "_start_watchdog": _start_watchdog,
        "_stop_watchdog": _stop_watchdog,
        "_ensure_profiles_dir": _ensure_profiles_dir,
        "_generate_self_signed_cert": _generate_self_signed_cert,
        "_get_tailscale_cert": _get_tailscale_cert,
        "_check_rate_limit_v2": _check_rate_limit_v2,
        "_run_sandboxed": _run_sandboxed,
        "_get_node_id": _get_node_id,
        "_cluster_heartbeat_loop": _cluster_heartbeat_loop,
        "_check_rate_limit": _check_rate_limit,
    })
    return registry


__all__ = ["build_runtime_wrappers"]
