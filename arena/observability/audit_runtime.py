"""Audit/webhook runtime wrapper for bridge wiring."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.observability.audit import audit_lock, read_tail as audit_read_tail, sanitize_audit_event as audit_sanitize_event, write_audit_event
from arena.observability.webhooks import fire_webhooks, load_webhooks, save_webhooks


@dataclass(frozen=True)
class AuditRuntimeContext:
    audit_path: Path
    app_dir: Path
    webhooks_file: Path
    utc_now: Callable[[], str]
    slow_executor: Executor
    log_debug: Callable[..., None]


@dataclass(frozen=True)
class AuditRuntime:
    sanitize_audit_event: Callable[[dict[str, Any]], dict[str, Any]]
    load_webhooks: Callable[[], dict[str, Any]]
    save_webhooks: Callable[[dict[str, Any]], None]
    fire_webhooks: Callable[[dict[str, Any]], None]
    audit: Callable[[dict[str, Any]], None]
    read_tail: Callable[..., list[str]]


def make_audit_runtime(ctx: AuditRuntimeContext) -> AuditRuntime:
    def sanitize_audit_event(event: dict[str, Any]) -> dict[str, Any]:
        return audit_sanitize_event(event)

    def _load_webhooks() -> dict[str, Any]:
        return load_webhooks(ctx.webhooks_file)

    def _save_webhooks(data: dict[str, Any]) -> None:
        return save_webhooks(ctx.webhooks_file, data)

    def _fire_webhooks(event: dict[str, Any]) -> None:
        return fire_webhooks(event, load_fn=_load_webhooks, log_debug=ctx.log_debug)

    def audit(event: dict[str, Any]) -> None:
        written = write_audit_event(
            event,
            audit_path=ctx.audit_path,
            app_dir=ctx.app_dir,
            utc_now_fn=ctx.utc_now,
            lock=audit_lock,
        )
        try:
            ctx.slow_executor.submit(_fire_webhooks, written)
        except Exception:
            pass

    def read_tail(path: Path, lines: int = 100) -> list[str]:
        return audit_read_tail(path, lines)

    return AuditRuntime(
        sanitize_audit_event=sanitize_audit_event,
        load_webhooks=_load_webhooks,
        save_webhooks=_save_webhooks,
        fire_webhooks=_fire_webhooks,
        audit=audit,
        read_tail=read_tail,
    )
