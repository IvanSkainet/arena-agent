"""Legacy memory and observability handler wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_memory_observability_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build memory/recall and audit/webhook observability handler registries."""
    globals().update(g)
    registry: dict[str, Callable] = {}

    memory_handler_ctx = MemoryHandlerContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        executor=_EXECUTOR,
        search_facts_paged=_search_facts_paged,
        write_fact=_write_fact,
        delete_fact=_delete_fact,
        recall_sync=_recall_sync,
        recall_digest_sync=_recall_digest_sync,
        audit=audit,
        utc_now=utc_now,
    )
    memory_handlers = make_memory_handlers(memory_handler_ctx)
    export_handler_attrs(registry, memory_handlers, {"handle_v1_memory": "memory_get", "handle_v1_memory_set": "memory_set", "handle_v1_memory_delete": "memory_delete", "handle_v1_recall": "recall", "handle_v1_recall_digest": "recall_digest"})

    def _audit_stats_sync() -> dict:
        return audit_stats(AUDIT)

    observability_handler_ctx = ObservabilityHandlerContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        executor=_EXECUTOR,
        audit_path=AUDIT,
        request_log_file=_REQ_LOG_FILE,
        read_tail=read_tail,
        read_request_log=read_request_log,
        audit_stats_sync=_audit_stats_sync,
        load_webhooks=_load_webhooks,
        save_webhooks=_save_webhooks,
        normalize_webhooks_config=normalize_webhooks_config,
        audit=audit,
    )
    observability_handlers = make_observability_handlers(observability_handler_ctx)
    export_handler_attrs(registry, observability_handlers, {"handle_v1_audit": "audit", "handle_v1_audit_stats": "audit_stats", "handle_v1_audit_log": "audit_log", "handle_v1_webhooks_get": "webhooks_get", "handle_v1_webhooks_set": "webhooks_set"})
    registry.update({
        "_memory_handler_ctx": memory_handler_ctx,
        "_memory_handlers": memory_handlers,
        "_audit_stats_sync": _audit_stats_sync,
        "_observability_handler_ctx": observability_handler_ctx,
        "_observability_handlers": observability_handlers,
    })
    return registry


__all__ = ["build_memory_observability_registries"]
