"""Runtime state and polling loop for file watchers."""
from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.files.sandbox import validate_watch_target
from arena.filewatch.snapshots import SnapshotPolicy, _snapshot


@dataclass(frozen=True)
class FileWatchRuntimeContext:
    home: Path
    default_root: Path | Callable[[], Path]
    emit_event: Any
    utc_now: Any
    log_info: Any
    log_warning: Any
    poll_interval_s: float = 2.0
    max_files_per_watch: int = 500


@dataclass(frozen=True)
class FileWatchRuntime:
    list_sync: Any
    add_sync: Any
    remove_sync: Any
    loop: Any
    state: dict[str, Any]



def make_file_watch_runtime(ctx: FileWatchRuntimeContext) -> FileWatchRuntime:
    state: dict[str, Any] = {"watchers": {}, "lock": threading.Lock()}

    def list_sync() -> dict[str, Any]:
        with state["lock"]:
            watchers = [
                {
                    "id": wid,
                    "path": meta["path"],
                    "recursive": meta["recursive"],
                    "patterns": list(meta["patterns"]),
                    "label": meta["label"],
                    "created_at": meta["created_at"],
                    "last_scan_ts": meta.get("last_scan_ts"),
                    "file_count": len(meta.get("snapshot", {})),
                    "truncated": bool(meta.get("truncated", False)),
                }
                for wid, meta in sorted(state["watchers"].items())
            ]
        return {"ok": True, "count": len(watchers), "watchers": watchers}

    def add_sync(
        *,
        path: str,
        root: str | Path | None = None,
        recursive: bool = True,
        patterns: list[str] | None = None,
        label: str = "",
        created_at: str = "",
    ) -> dict[str, Any]:
        registration = WatchRegistration(path, root, recursive, patterns, label, created_at)
        return _add_sync(ctx, state, registration)

    def remove_sync(watch_id: str) -> dict[str, Any]:
        with state["lock"]:
            meta = state["watchers"].pop(watch_id, None)
        if not meta:
            return {"ok": False, "error": "watch not found", "status": 404}
        return {"ok": True, "removed": watch_id, "path": meta["path"]}

    async def loop(_app) -> None:
        ctx.log_info("[FileWatch] watcher loop started")
        while True:
            with state["lock"]:
                current = [(wid, dict(meta)) for wid, meta in state["watchers"].items()]
            for wid, meta in current:
                await _poll_watch(ctx, wid, meta, state)
            await asyncio.sleep(ctx.poll_interval_s)

    return FileWatchRuntime(list_sync=list_sync, add_sync=add_sync, remove_sync=remove_sync, loop=loop, state=state)


def _clean_patterns(patterns: list[str] | None) -> list[str]:
    return [str(pattern).strip() for pattern in (patterns or []) if str(pattern).strip()][:20]


@dataclass(frozen=True)
class WatchRegistration:
    path: str
    root: str | Path | None
    recursive: bool
    patterns: list[str] | None
    label: str
    created_at: str


def _add_sync(ctx: FileWatchRuntimeContext, state: dict,
              registration: WatchRegistration) -> dict[str, Any]:
    path, root = registration.path, registration.root
    recursive, patterns = registration.recursive, registration.patterns
    label, created_at = registration.label, registration.created_at
    default = ctx.default_root() if callable(ctx.default_root) else ctx.default_root
    root_path = Path(root or default).expanduser().resolve()
    resolved, error, status = validate_watch_target(path, root=root_path, home=ctx.home)
    if resolved is None:
        return {"ok": False, "error": error, "status": status}
    clean_patterns = _clean_patterns(patterns)
    try:
        if not resolved.exists():
            return {"ok": False, "error": "path not found", "status": 404}
        snapshot, truncated = _snapshot(
            resolved, SnapshotPolicy(bool(recursive), clean_patterns, ctx.max_files_per_watch,
                (root_path, ctx.home)),
        )
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"watch path is not usable ({type(exc).__name__})", "status": 400}
    wid = uuid.uuid4().hex[:10]
    meta = {
        "path": str(resolved),
        "root": str(root_path),
        "recursive": bool(recursive),
        "patterns": clean_patterns,
        "label": str(label or "").strip(),
        "created_at": created_at or ctx.utc_now(),
        "last_scan_ts": created_at or ctx.utc_now(),
        "snapshot": snapshot,
        "truncated": truncated,
    }
    with state["lock"]:
        state["watchers"][wid] = meta
    return {
        "ok": True,
        "id": wid,
        "path": meta["path"],
        "recursive": meta["recursive"],
        "patterns": list(meta["patterns"]),
        "label": meta["label"],
        "created_at": meta["created_at"],
        "last_scan_ts": meta["last_scan_ts"],
        "file_count": len(meta["snapshot"]),
        "truncated": truncated,
    }


async def _poll_watch(ctx: FileWatchRuntimeContext, wid: str, meta: dict, state: dict) -> None:
    path = Path(meta["path"])
    try:
        snapshot, truncated = _snapshot(
            path, SnapshotPolicy(meta["recursive"], list(meta["patterns"]), ctx.max_files_per_watch,
                                 (Path(meta["root"]), ctx.home)),
        )
    except FileNotFoundError:
        snapshot, truncated = {}, False
    previous = meta.get("snapshot", {})
    events = _changes(previous, snapshot)
    with state["lock"]:
        if wid in state["watchers"]:
            state["watchers"][wid]["snapshot"] = snapshot
            state["watchers"][wid]["truncated"] = truncated
            state["watchers"][wid]["last_scan_ts"] = ctx.utc_now()
    for event_name, changed_path in events[:100]:
        await ctx.emit_event(
            "file_watch_change",
            {
                "watch_id": wid,
                "watch_path": meta["path"],
                "label": meta["label"],
                "event": event_name,
                "path": changed_path,
            },
        )
    if truncated:
        ctx.log_warning("[FileWatch] %s hit max file scan limit (%d)", meta["path"], ctx.max_files_per_watch)


def _changes(previous: dict, snapshot: dict) -> list[tuple[str, str]]:
    events = []
    for changed in sorted(snapshot.keys() - previous.keys()):
        events.append(("added", changed))
    for changed in sorted(previous.keys() - snapshot.keys()):
        events.append(("deleted", changed))
    for changed in sorted(snapshot.keys() & previous.keys()):
        if snapshot[changed] != previous[changed]:
            events.append(("modified", changed))
    return events
