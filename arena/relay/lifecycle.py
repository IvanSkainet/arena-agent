"""Durable relay lifecycle and fresh-session resume state.

Queue claiming stays in :mod:`arena.relay.store`; this module overlays the
operator-visible lifecycle on the claimed message archive without duplicating
message bytes or introducing a second queue.
"""
from __future__ import annotations

import contextlib
import glob
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from arena.relay import store

try:  # pragma: no cover - platform-selected import
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
try:  # pragma: no cover - platform-selected import
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None  # type: ignore[assignment]

LIFECYCLE_LOCK_TIMEOUT_S = 5.0


def _claimed_message_path(root: Path, message_id: str) -> Path | None:
    _inbox, claimed, _replies = store._dirs(root)
    wanted = store.validate_message_id(message_id)
    for path in sorted(claimed.glob(f"*-{glob.escape(wanted)}.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict) and str(raw.get("id") or "") == wanted:
            return path
    return None


@contextmanager
def _lifecycle_update_lock(
    root: Path,
    message_id: str,
    *,
    now: Any = time.monotonic,
    sleep: Any = time.sleep,
) -> Iterator[None]:
    """Serialize one claimed message's read-modify-write across processes.

    The OS releases an advisory lock when a process exits, so a killed Arena
    session cannot leave a stale owner behind. The persistent empty lock file is
    only the shared locking inode, not an ownership marker.
    """
    wanted = store.validate_message_id(message_id)
    _inbox, claimed, _replies = store._dirs(root)
    lock = claimed / f".{wanted}.lifecycle.lock"
    try:
        handle = lock.open("a+b")
    except OSError as exc:
        raise ValueError(f"relay lifecycle lock failed: {wanted}") from exc

    deadline = float(now()) + LIFECYCLE_LOCK_TIMEOUT_S
    acquired = False
    try:
        while not acquired:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt is not None:  # pragma: no cover - Windows only
                    if os.fstat(handle.fileno()).st_size == 0:
                        handle.write(b"\0")
                        handle.flush()
                    handle.seek(0)
                    getattr(msvcrt, "locking")(
                        handle.fileno(), getattr(msvcrt, "LK_NBLCK"), 1
                    )
                else:  # pragma: no cover - unsupported Python platform
                    raise RuntimeError("no supported file-locking primitive")
                acquired = True
            except (BlockingIOError, OSError):
                if float(now()) >= deadline:
                    raise ValueError(
                        f"relay lifecycle update is busy: {wanted}"
                    ) from None
                sleep(0.01)
        yield
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:  # pragma: no cover - Windows only
                    handle.seek(0)
                    getattr(msvcrt, "locking")(
                        handle.fileno(), getattr(msvcrt, "LK_UNLCK"), 1
                    )
        handle.close()


def _update_claimed_message(
    root: Path,
    message_id: str,
    *,
    meta_updates: dict[str, Any] | None = None,
    **changes: Any,
) -> store.RelayMessage:
    with _lifecycle_update_lock(root, message_id):
        path = _claimed_message_path(root, message_id)
        if path is None:
            raise ValueError(f"claimed relay message not found: {message_id}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"claimed relay message is unreadable: {message_id}") from exc
        # A correlated reply is terminal. A stale concurrent busy writer must
        # never make completed work resumable again.
        if raw.get("lifecycle") == "replied" and changes.get("lifecycle") != "replied":
            raise ValueError(f"claimed relay message is not resumable: {message_id}")
        raw.update(changes)
        if meta_updates:
            current_meta = raw.get("meta")
            merged_meta = dict(current_meta) if isinstance(current_meta, dict) else {}
            merged_meta.update(meta_updates)
            raw["meta"] = merged_meta
        store._write_atomic(path, raw)
        return store.RelayMessage.from_dict(raw)


def mark_busy(
    root: Path,
    message_id: str,
    *,
    claimed_by: str = "",
    kind: str = "",
) -> store.RelayMessage:
    """Mark a claimed message as actively processed by an agent session."""
    current = resume_claimed(root, message_id)
    if current is None:
        raise ValueError(f"claimed relay message is not resumable: {message_id}")
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in {"", "message", "turn", "repair"}:
        raise ValueError(f"unsupported relay message kind: {kind}")
    meta_updates = {"kind": normalized_kind} if normalized_kind else None
    return _update_claimed_message(
        root,
        message_id,
        lifecycle="busy",
        busy_at=time.time(),
        claimed_by=str(claimed_by or "")[:128],
        meta_updates=meta_updates,
    )


def mark_replied(
    root: Path,
    message_id: str,
    *,
    replied_at: float,
    reply_id: str,
) -> store.RelayMessage:
    return _update_claimed_message(
        root,
        message_id,
        lifecycle="replied",
        replied_at=replied_at,
        reply_id=reply_id,
    )


def resume_claimed(root: Path, message_id: str = "") -> store.RelayMessage | None:
    """Read durable unfinished work after an agent session restart.

    This is deliberately explicit rather than part of ``claim_next``. A new
    session first inspects status, then resumes only when the previous session
    is known to be gone. Re-reading claimed work automatically on every poll
    would let two live sessions author the same turn concurrently.
    """
    _inbox, claimed, replies = store._dirs(root)
    replied_targets: set[str] = set()
    for reply_path in replies.glob("*.json"):
        try:
            reply_raw = json.loads(reply_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        reply_meta = reply_raw.get("meta") if isinstance(reply_raw, dict) else None
        target = str(
            reply_meta.get("in_reply_to") if isinstance(reply_meta, dict) else ""
        )
        if target:
            replied_targets.add(target)

    wanted = str(message_id or "").strip()
    if wanted:
        exact = _claimed_message_path(root, wanted)
        candidates = [exact] if exact is not None else []
    else:
        candidates = sorted(claimed.glob("*.json"))
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict) or "lifecycle" not in raw:
            # Pre-lifecycle claimed files are indeterminate history. Existing
            # installs retained them after replies were read, so exposing them
            # would fabricate a backlog for a fresh agent session.
            continue
        try:
            msg = store.RelayMessage.from_dict(raw)
        except (TypeError, ValueError):
            continue
        if wanted and msg.id != wanted:
            continue
        if msg.lifecycle == "replied" or msg.id in replied_targets:
            continue
        if msg.lifecycle not in {"claimed", "busy"}:
            msg.lifecycle = "claimed"
        return msg
    return None


def outstanding_depth(root: Path) -> int:
    """Count unique claimed/busy records for the hot empty-poll path."""
    _inbox, claimed, _replies = store._dirs(root)
    outstanding_ids: set[str] = set()
    for path in claimed.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict) or "lifecycle" not in raw:
            continue
        message_id = str(raw.get("id") or "")
        if message_id and raw.get("lifecycle") != "replied":
            outstanding_ids.add(message_id)
    return len(outstanding_ids)


def relay_snapshot(root: Path, *, limit: int = 50) -> dict[str, Any]:
    """Return exact lifecycle depths and bounded body-free metadata."""
    inbox, claimed, replies = store._dirs(root)
    summaries_by_id: dict[str, dict[str, Any]] = {}
    counts = {"queued": 0, "claimed": 0, "busy": 0, "replied": 0}

    def read_message(path: Path, folder: str) -> dict[str, Any] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        if folder == "claimed" and "lifecycle" not in raw:
            return None
        try:
            msg = store.RelayMessage.from_dict(raw)
        except (TypeError, ValueError):
            return None
        if not msg.id:
            return None
        lifecycle = msg.lifecycle
        if folder == "inbox":
            lifecycle = "queued"
        elif lifecycle not in {"busy", "replied"}:
            lifecycle = "claimed"
        meta = msg.meta if isinstance(msg.meta, dict) else {}
        kind = str(
            meta.get("kind")
            or meta.get("dispatch_kind")
            or meta.get("type")
            or "message"
        )
        return {
            "id": msg.id,
            "lifecycle": lifecycle,
            "kind": kind,
            "sender": msg.sender,
            "created_at": msg.created_at,
            "claimed_at": msg.claimed_at,
            "busy_at": msg.busy_at,
            "replied_at": msg.replied_at,
            "claimed_by": msg.claimed_by,
            "reply_id": msg.reply_id,
            "transport": str(meta.get("transport") or ""),
            "source": str(meta.get("source") or ""),
            "sequence": meta.get("sequence"),
        }

    for path in sorted(inbox.glob("*.json")):
        summary = read_message(path, "inbox")
        if summary is not None:
            summaries_by_id.setdefault(summary["id"], summary)
    for path in sorted(claimed.glob("*.json")):
        summary = read_message(path, "claimed")
        if summary is not None:
            # A claimed copy wins when a failed Windows move leaves the locked
            # inbox name behind. Counting both would invent queued work.
            summaries_by_id[summary["id"]] = summary

    summaries = sorted(
        summaries_by_id.values(),
        key=lambda item: (float(item.get("created_at") or 0.0), item["id"]),
    )
    for item in summaries:
        counts[item["lifecycle"]] += 1
    bounded = summaries[: max(0, min(int(limit), 200))]
    poll_age = store.agent_poll_age(root)
    return {
        "queued_depth": counts["queued"],
        "claimed_depth": counts["claimed"],
        "busy_depth": counts["busy"],
        "replied_depth": counts["replied"],
        "outstanding_depth": counts["claimed"] + counts["busy"],
        "repair_depth": sum(
            1
            for item in summaries
            if item["kind"] == "repair" and item["lifecycle"] != "replied"
        ),
        "reply_depth": len(list(replies.glob("*.json"))),
        "last_poll_age_s": poll_age,
        "agent_polling": poll_age is not None and poll_age < store.POLL_FRESH_S,
        "messages": bounded,
        "truncated": len(bounded) < len(summaries),
    }
