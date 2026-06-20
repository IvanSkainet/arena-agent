"""Runtime state and polling loop for file watchers."""
from __future__ import annotations

import asyncio
import fnmatch
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileWatchRuntimeContext:
    home: Path
    default_root: Path
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



def _matches(path: Path, patterns: list[str]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(path.name, pat) for pat in patterns)


def _snapshot(path: Path, recursive: bool, patterns: list[str], max_files: int) -> tuple[dict[str, tuple[int, int]], bool]:
    files: dict[str, tuple[int, int]] = {}
    truncated = False
    if path.is_file():
        st = path.stat()
        files[str(path)] = (st.st_mtime_ns, st.st_size)
        return files, False
    iterator = path.rglob("*") if recursive else path.glob("*")
    for entry in iterator:
        if not entry.is_file() or not _matches(entry, patterns):
            continue
        st = entry.stat()
        files[str(entry)] = (st.st_mtime_ns, st.st_size)
        if len(files) >= max_files:
            truncated = True
            break
    return files, truncated



def _resolve_target(target: str, *, root: Path, home: Path) -> Path:
    p = Path(target).expanduser()
    if not p.is_absolute():
        p = root / p
    resolved = p.resolve()
    resolved.relative_to(home.resolve())
    return resolved



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
        root_path = Path(root or ctx.default_root)
        resolved = _resolve_target(path, root=root_path, home=ctx.home)
        if not resolved.exists():
            return {"ok": False, "error": "path not found", "status": 404}
        clean_patterns = [str(p).strip() for p in (patterns or []) if str(p).strip()][:20]
        snapshot, truncated = _snapshot(resolved, bool(recursive), clean_patterns, ctx.max_files_per_watch)
        wid = uuid.uuid4().hex[:10]
        meta = {
            "path": str(resolved),
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
                path = Path(meta["path"])
                try:
                    snapshot, truncated = _snapshot(path, meta["recursive"], list(meta["patterns"]), ctx.max_files_per_watch)
                except FileNotFoundError:
                    snapshot, truncated = {}, False
                previous = meta.get("snapshot", {})
                events = []
                for changed in sorted(snapshot.keys() - previous.keys()):
                    events.append(("added", changed))
                for changed in sorted(previous.keys() - snapshot.keys()):
                    events.append(("deleted", changed))
                for changed in sorted(snapshot.keys() & previous.keys()):
                    if snapshot[changed] != previous[changed]:
                        events.append(("modified", changed))
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
            await asyncio.sleep(ctx.poll_interval_s)

    return FileWatchRuntime(list_sync=list_sync, add_sync=add_sync, remove_sync=remove_sync, loop=loop, state=state)
