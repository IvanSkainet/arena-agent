"""audit, error middleware and env.log-cleanup runtime wiring."""
from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from arena.wiring.env import RuntimeEnv


def build_observability_runtimes(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build audit/webhook runtime, error middleware, and env.log-cleanup globals."""
    env = RuntimeEnv(g)
    registry: dict[str, Any] = {}

    audit_runtime_ctx = env.AuditRuntimeContext(
        audit_path=env.AUDIT,
        app_dir=env.APP_DIR,
        webhooks_file=Path(os.environ.get("ARENA_AGENT_HOME", str(env.BRIDGE_DIR))).expanduser() / "webhooks.json",
        utc_now=env.utc_now,
        slow_executor=env._SLOW_EXECUTOR,
        log_debug=env.log.debug,
    )
    audit_runtime = env.make_audit_runtime(audit_runtime_ctx)
    registry.update({
        "_audit_runtime_ctx": audit_runtime_ctx,
        "_audit_runtime": audit_runtime,
        "sanitize_audit_event": audit_runtime.sanitize_audit_event,
        "_load_webhooks": audit_runtime.load_webhooks,
        "_save_webhooks": audit_runtime.save_webhooks,
        "_fire_webhooks": audit_runtime.fire_webhooks,
        "audit": audit_runtime.audit,
        "read_tail": audit_runtime.read_tail,
    })

    error_middleware_ctx = env.ErrorMiddlewareContext(
        check_rate_limit_v2=env._check_rate_limit_v2,
        check_rate_limit=env._check_rate_limit,
        record_request=env._record_request,
        log_request_response=env._log_request_response,
        cors_json_response=env._cors_json_response,
        audit=audit_runtime.audit,
        log_debug=env.log.debug,
        log_warning=env.log.warning,
        log_error=env.log.error,
    )
    registry["_error_middleware_ctx"] = error_middleware_ctx
    registry["error_middleware"] = env.make_error_middleware(error_middleware_ctx)

    max_log_size = 10 * 1024 * 1024
    max_log_backups = 3
    log_files_to_rotate = [env.APP_DIR / "bridge.log", env.APP_DIR / "requests.jsonl", env.APP_DIR / "audit.jsonl"]
    log_cleanup_ctx = env.LogCleanupContext(
        app_dir=env.APP_DIR,
        log_files=log_files_to_rotate,
        max_log_size=max_log_size,
        max_log_backups=max_log_backups,
        log_info=env.log.info,
        log_warning=env.log.warning,
        log_critical=env.log.critical,
        log_error=env.log.error,
    )
    log_cleanup_runtime = env.make_log_cleanup_runtime(log_cleanup_ctx)
    registry.update({
        "_MAX_LOG_SIZE": max_log_size,
        "_MAX_LOG_BACKUPS": max_log_backups,
        "_LOG_FILES_TO_ROTATE": log_files_to_rotate,
        "_log_cleanup_ctx": log_cleanup_ctx,
        "_log_cleanup_runtime": log_cleanup_runtime,
        "_rotate_file_if_oversized": log_cleanup_runtime.rotate_file_if_oversized,
        "_rotate_all_logs_on_startup": log_cleanup_runtime.rotate_all_logs_on_startup,
        "_check_disk_space": log_cleanup_runtime.check_disk_space,
        "_log_cleanup_loop": log_cleanup_runtime.log_cleanup_loop,
    })
    return registry


__all__ = ["build_observability_runtimes"]
