"""Memory runtime compatibility wrappers."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.memory.profiles import DEFAULT_MEMORY_PROFILE
from arena.memory.store import delete_fact, init_memory_db, list_profiles, load_facts, recall, recall_digest, search_facts_paged, write_fact


@dataclass(frozen=True)
class MemoryRuntimeContext:
    db_path: Path
    jsonl_path: Path
    audit_path: Path
    read_tail: Callable[..., list[str]]
    utc_now: Callable[[], str]
    log_error: Callable[..., None]


@dataclass(frozen=True)
class MemoryRuntime:
    init_memory_db: Callable[[], None]
    load_facts: Callable[..., list[dict[str, Any]]]
    list_profiles: Callable[[], list[str]]
    search_facts_paged: Callable[..., tuple[int, list[dict[str, Any]]]]
    write_fact: Callable[[dict[str, Any]], None]
    delete_fact: Callable[..., bool]
    recall_sync: Callable[..., dict[str, Any]]
    recall_digest_sync: Callable[..., dict[str, Any]]


def make_memory_runtime(ctx: MemoryRuntimeContext) -> MemoryRuntime:
    def _init_memory_db() -> None:
        return init_memory_db(db_path=ctx.db_path, jsonl_path=ctx.jsonl_path, log_error=ctx.log_error)

    def _load_facts(profile: str | None = DEFAULT_MEMORY_PROFILE) -> list[dict[str, Any]]:
        return load_facts(ctx.db_path, profile=profile)

    def _list_profiles() -> list[str]:
        return list_profiles(ctx.db_path)

    def _search_facts_paged(
        q: str = "", offset: int = 0, limit: int = 100, profile: str | None = DEFAULT_MEMORY_PROFILE
    ) -> tuple[int, list[dict[str, Any]]]:
        return search_facts_paged(ctx.db_path, q=q, offset=offset, limit=limit, profile=profile, log_error=ctx.log_error)

    def _write_fact(entry: dict[str, Any]) -> None:
        return write_fact(ctx.db_path, entry)

    def _delete_fact(key: str, profile: str | None = DEFAULT_MEMORY_PROFILE) -> bool:
        return delete_fact(ctx.db_path, key, profile=profile)

    def _recall_sync(query: str, top: int, profile: str | None = DEFAULT_MEMORY_PROFILE) -> dict[str, Any]:
        return recall(query, facts=_load_facts(profile=profile), top=top)

    def _recall_digest_sync(profile: str | None = DEFAULT_MEMORY_PROFILE) -> dict[str, Any]:
        result = recall_digest(facts=_load_facts(profile=profile), audit_lines=ctx.read_tail(ctx.audit_path, 20), utc_now_fn=ctx.utc_now)
        result["profile"] = profile if profile is not None else "all"
        return result

    return MemoryRuntime(
        init_memory_db=_init_memory_db,
        load_facts=_load_facts,
        list_profiles=_list_profiles,
        search_facts_paged=_search_facts_paged,
        write_fact=_write_fact,
        delete_fact=_delete_fact,
        recall_sync=_recall_sync,
        recall_digest_sync=_recall_digest_sync,
    )
