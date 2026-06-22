"""runtime object wiring extracted from unified_bridge.py."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from arena.wiring.env import RuntimeEnv


def build_memory_resource_browser_runtimes(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build memory/resource/browser runtimes and their compatibility globals."""
    env = RuntimeEnv(g)
    registry: dict[str, Any] = {}

    memory_runtime_ctx = env.MemoryRuntimeContext(
        db_path=env.MEMORY_DB,
        jsonl_path=env.MEMORY_FILE,
        audit_path=env.AUDIT,
        read_tail=env.read_tail,
        utc_now=env.utc_now,
        log_error=env.log.error,
    )
    memory_runtime = env.make_memory_runtime(memory_runtime_ctx)
    registry.update({
        "_memory_runtime_ctx": memory_runtime_ctx,
        "_memory_runtime": memory_runtime,
        "init_memory_db": memory_runtime.init_memory_db,
        "_load_facts": memory_runtime.load_facts,
        "_list_memory_profiles": memory_runtime.list_profiles,
        "_search_facts_paged": memory_runtime.search_facts_paged,
        "_write_fact": memory_runtime.write_fact,
        "_delete_fact": memory_runtime.delete_fact,
        "_recall_sync": memory_runtime.recall_sync,
        "_recall_digest_sync": memory_runtime.recall_digest_sync,
    })

    resource_runtime_ctx = env.ResourceRuntimeContext(
        missions_dir=env.MISSIONS_DIR,
        reports_dir=env.REPORTS_DIR,
        hooks_dir=env.HOOKS_DIR,
        agents_dir=env.AGENTS_DIR,
        subagents_dir=env.SUBAGENTS_DIR,
        bin_dir=env.BIN,
        root_agent=env.ROOT_AGENT,
        build_plan=env.build_plan,
        subprocess_kwargs=env._subprocess_kwargs,
    )
    resource_runtime = env.make_resource_runtime(resource_runtime_ctx)
    registry.update({
        "_resource_runtime_ctx": resource_runtime_ctx,
        "_resource_runtime": resource_runtime,
        "_list_missions_sync": resource_runtime.list_missions_sync,
        "_list_reports_sync": resource_runtime.list_reports_sync,
        "_mission_templates_sync": resource_runtime.mission_templates_sync,
        "_mission_compose_sync": resource_runtime.mission_compose_sync,
        "_mission_create_sync": resource_runtime.mission_create_sync,
        "_mission_run_sync": resource_runtime.mission_run_sync,
    })

    browser_runtime_ctx = env.BrowserRuntimeContext(
        version=env.VERSION,
        validate_url=env._validate_url,
    )
    browser_runtime = env.make_browser_runtime(browser_runtime_ctx)
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
