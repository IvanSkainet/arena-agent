# ruff: noqa: F821
"""Legacy audit, error middleware and log-cleanup runtime wiring."""
from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any


def build_observability_runtimes(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build audit/webhook runtime, error middleware, and log-cleanup globals."""
    globals().update(g)
    registry: dict[str, Any] = {}

    audit_runtime_ctx = AuditRuntimeContext(
        audit_path=AUDIT,
        app_dir=APP_DIR,
        webhooks_file=Path(os.environ.get("ARENA_AGENT_HOME", str(BRIDGE_DIR))).expanduser() / "webhooks.json",
        utc_now=utc_now,
        slow_executor=_SLOW_EXECUTOR,
        log_debug=log.debug,
    )
    audit_runtime = make_audit_runtime(audit_runtime_ctx)
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

    error_middleware_ctx = ErrorMiddlewareContext(
        check_rate_limit_v2=_check_rate_limit_v2,
        check_rate_limit=_check_rate_limit,
        record_request=_record_request,
        log_request_response=_log_request_response,
        cors_json_response=_cors_json_response,
        audit=audit_runtime.audit,
        log_debug=log.debug,
        log_warning=log.warning,
        log_error=log.error,
    )
    registry["_error_middleware_ctx"] = error_middleware_ctx
    registry["error_middleware"] = make_error_middleware(error_middleware_ctx)

    max_log_size = 10 * 1024 * 1024
    max_log_backups = 3
    log_files_to_rotate = [APP_DIR / "bridge.log", APP_DIR / "requests.jsonl", APP_DIR / "audit.jsonl"]
    log_cleanup_ctx = LogCleanupContext(
        app_dir=APP_DIR,
        log_files=log_files_to_rotate,
        max_log_size=max_log_size,
        max_log_backups=max_log_backups,
        log_info=log.info,
        log_warning=log.warning,
        log_critical=log.critical,
        log_error=log.error,
    )
    log_cleanup_runtime = make_log_cleanup_runtime(log_cleanup_ctx)
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
