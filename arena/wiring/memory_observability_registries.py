"""memory and observability handler wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv


def build_memory_observability_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build memory/recall and env.audit/webhook observability handler registries."""
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    memory_handler_ctx = env.MemoryHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        search_facts_paged=env._search_facts_paged,
        list_profiles=env._list_memory_profiles,
        write_fact=env._write_fact,
        delete_fact=env._delete_fact,
        recall_sync=env._recall_sync,
        recall_digest_sync=env._recall_digest_sync,
        audit=env.audit,
        utc_now=env.utc_now,
    )
    memory_handlers = env.make_memory_handlers(memory_handler_ctx)
    env.export_handler_attrs(registry, memory_handlers, {"handle_v1_memory": "memory_get", "handle_v1_memory_set": "memory_set", "handle_v1_memory_delete": "memory_delete", "handle_v1_recall": "recall", "handle_v1_recall_digest": "recall_digest"})

    def _audit_stats_sync() -> dict:
        return env.audit_stats(env.AUDIT)

    observability_handler_ctx = env.ObservabilityHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        audit_path=env.AUDIT,
        request_log_file=env._REQ_LOG_FILE,
        read_tail=env.read_tail,
        read_request_log=env.read_request_log,
        audit_stats_sync=_audit_stats_sync,
        load_webhooks=env._load_webhooks,
        save_webhooks=env._save_webhooks,
        normalize_webhooks_config=env.normalize_webhooks_config,
        audit=env.audit,
    )
    observability_handlers = env.make_observability_handlers(observability_handler_ctx)
    env.export_handler_attrs(registry, observability_handlers, {"handle_v1_audit": "audit", "handle_v1_audit_stats": "audit_stats", "handle_v1_audit_log": "audit_log", "handle_v1_webhooks_get": "webhooks_get", "handle_v1_webhooks_set": "webhooks_set", "handle_v1_audit_stream": "audit_stream"})
    registry.update({
        "_memory_handler_ctx": memory_handler_ctx,
        "_memory_handlers": memory_handlers,
        "_audit_stats_sync": _audit_stats_sync,
        "_observability_handler_ctx": observability_handler_ctx,
        "_observability_handlers": observability_handlers,
    })
    return registry


__all__ = ["build_memory_observability_registries"]
