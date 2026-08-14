"""Durable relay lifecycle and fresh-session resume state.

Queue claiming stays in :mod:`arena.relay.store`; this module overlays the
operator-visible lifecycle on the claimed message archive without duplicating
message bytes or introducing a second queue.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from arena.relay import store


def _claimed_message_path(root: Path, message_id: str) -> Path | None:
    _inbox, claimed, _replies = store._dirs(root)
    wanted = str(message_id or "").strip()
    if not wanted:
        return None
    for path in sorted(claimed.glob(f"*-{wanted}.json")):
        return path
    return None


def _update_claimed_message(
    root: Path,
    message_id: str,
    **changes: Any,
) -> store.RelayMessage:
    path = _claimed_message_path(root, message_id)
    if path is None:
        raise ValueError(f"claimed relay message not found: {message_id}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"claimed relay message is unreadable: {message_id}") from exc
    raw.update(changes)
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
    meta = dict(current.meta)
    if normalized_kind:
        meta["kind"] = normalized_kind
    return _update_claimed_message(
        root,
        message_id,
        lifecycle="busy",
        busy_at=time.time(),
        claimed_by=str(claimed_by or "")[:128],
        meta=meta,
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
        target = str((reply_raw.get("meta") or {}).get("in_reply_to") or "")
        if target:
            replied_targets.add(target)

    wanted = str(message_id or "").strip()
    for path in sorted(claimed.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict) or "lifecycle" not in raw:
            # Pre-lifecycle claimed files are indeterminate history. Existing
            # installs retained them after replies were read, so exposing them
            # would fabricate a backlog for a fresh agent session.
            continue
        msg = store.RelayMessage.from_dict(raw)
        if wanted and msg.id != wanted:
            continue
        if msg.lifecycle == "replied" or msg.id in replied_targets:
            continue
        if msg.lifecycle not in {"claimed", "busy"}:
            msg.lifecycle = "claimed"
        return msg
    return None


def relay_snapshot(root: Path, *, limit: int = 50) -> dict[str, Any]:
    """Return bounded lifecycle state without exposing message bodies."""
    inbox, claimed, replies = store._dirs(root)
    summaries: list[dict[str, Any]] = []
    counts = {"queued": 0, "claimed": 0, "busy": 0, "replied": 0}

    def append_message(path: Path, folder: str) -> None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        if folder == "claimed" and "lifecycle" not in raw:
            return
        msg = store.RelayMessage.from_dict(raw)
        lifecycle = msg.lifecycle
        if folder == "inbox":
            lifecycle = "queued"
        elif lifecycle not in {"busy", "replied"}:
            lifecycle = "claimed"
        counts[lifecycle] += 1
        meta = msg.meta if isinstance(msg.meta, dict) else {}
        kind = str(
            meta.get("kind")
            or meta.get("dispatch_kind")
            or meta.get("type")
            or "message"
        )
        summaries.append(
            {
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
        )

    for path in sorted(inbox.glob("*.json")):
        append_message(path, "inbox")
    for path in sorted(claimed.glob("*.json")):
        append_message(path, "claimed")

    summaries.sort(key=lambda item: (float(item.get("created_at") or 0.0), item["id"]))
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
