"""Memory runtime compatibility wrappers."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.memory.store import delete_fact, init_memory_db, load_facts, recall, recall_digest, search_facts_paged, write_fact


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
    load_facts: Callable[[], list[dict[str, Any]]]
    search_facts_paged: Callable[..., tuple[int, list[dict[str, Any]]]]
    write_fact: Callable[[dict[str, Any]], None]
    delete_fact: Callable[[str], bool]
    recall_sync: Callable[[str, int], dict[str, Any]]
    recall_digest_sync: Callable[[], dict[str, Any]]


def make_memory_runtime(ctx: MemoryRuntimeContext) -> MemoryRuntime:
    def _init_memory_db() -> None:
        return init_memory_db(db_path=ctx.db_path, jsonl_path=ctx.jsonl_path, log_error=ctx.log_error)

    def _load_facts() -> list[dict[str, Any]]:
        return load_facts(ctx.db_path)

    def _search_facts_paged(q: str = "", offset: int = 0, limit: int = 100) -> tuple[int, list[dict[str, Any]]]:
        return search_facts_paged(ctx.db_path, q=q, offset=offset, limit=limit, log_error=ctx.log_error)

    def _write_fact(entry: dict[str, Any]) -> None:
        return write_fact(ctx.db_path, entry)

    def _delete_fact(key: str) -> bool:
        return delete_fact(ctx.db_path, key)

    def _recall_sync(query: str, top: int) -> dict[str, Any]:
        return recall(query, facts=_load_facts(), top=top)

    def _recall_digest_sync() -> dict[str, Any]:
        return recall_digest(facts=_load_facts(), audit_lines=ctx.read_tail(ctx.audit_path, 20), utc_now_fn=ctx.utc_now)

    return MemoryRuntime(
        init_memory_db=_init_memory_db,
        load_facts=_load_facts,
        search_facts_paged=_search_facts_paged,
        write_fact=_write_fact,
        delete_fact=_delete_fact,
        recall_sync=_recall_sync,
        recall_digest_sync=_recall_digest_sync,
    )
