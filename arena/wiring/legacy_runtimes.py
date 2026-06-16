# ruff: noqa: F821
"""Legacy runtime object wiring extracted from unified_bridge.py."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


def build_memory_resource_browser_runtimes(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build memory/resource/browser runtimes and their compatibility globals."""
    globals().update(g)
    registry: dict[str, Any] = {}

    memory_runtime_ctx = MemoryRuntimeContext(
        db_path=MEMORY_DB,
        jsonl_path=MEMORY_FILE,
        audit_path=AUDIT,
        read_tail=read_tail,
        utc_now=utc_now,
        log_error=log.error,
    )
    memory_runtime = make_memory_runtime(memory_runtime_ctx)
    registry.update({
        "_memory_runtime_ctx": memory_runtime_ctx,
        "_memory_runtime": memory_runtime,
        "init_memory_db": memory_runtime.init_memory_db,
        "_load_facts": memory_runtime.load_facts,
        "_search_facts_paged": memory_runtime.search_facts_paged,
        "_write_fact": memory_runtime.write_fact,
        "_delete_fact": memory_runtime.delete_fact,
        "_recall_sync": memory_runtime.recall_sync,
        "_recall_digest_sync": memory_runtime.recall_digest_sync,
    })

    resource_runtime_ctx = ResourceRuntimeContext(
        missions_dir=MISSIONS_DIR,
        reports_dir=REPORTS_DIR,
        hooks_dir=HOOKS_DIR,
        agents_dir=AGENTS_DIR,
        subagents_dir=SUBAGENTS_DIR,
        bin_dir=BIN,
        subprocess_kwargs=_subprocess_kwargs,
    )
    resource_runtime = make_resource_runtime(resource_runtime_ctx)
    registry.update({
        "_resource_runtime_ctx": resource_runtime_ctx,
        "_resource_runtime": resource_runtime,
        "_list_missions_sync": resource_runtime.list_missions_sync,
        "_list_reports_sync": resource_runtime.list_reports_sync,
    })

    browser_runtime_ctx = BrowserRuntimeContext(
        version=VERSION,
        validate_url=_validate_url,
    )
    browser_runtime = make_browser_runtime(browser_runtime_ctx)
    registry.update({
        "_browser_runtime_ctx": browser_runtime_ctx,
        "_browser_runtime": browser_runtime,
        "_browser_search_sync": browser_runtime.browser_search_sync,
        "_browser_read_sync": browser_runtime.browser_read_sync,
        "_browser_dump_sync": browser_runtime.browser_dump_sync,
        "_browser_fetch_sync": browser_runtime.browser_fetch_sync,
        "_browser_head_sync": browser_runtime.browser_head_sync,
    })
    return registry


__all__ = ["build_memory_resource_browser_runtimes"]
