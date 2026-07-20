"""Agent session checkpoint — bug #9 seed.

Ivan's original observation (v4.59.1 session):
    "нужно доработать что-то вроде защиты при перезагрузке"

When the agent context is destroyed (browser restart, OS reboot, tab
close, network drop), any progress that lived only in the agent's
working memory is lost. The next session starts blind — it has git
history but no idea what the *previous* agent was trying to do, what
had been tried, what the next step was.

This module gives that next agent a place to look. Simple JSON file at
`~/.arena/agent_session.json` (override via ARENA_AGENT_SESSION_FILE
for tests):

    {
      "goal":         "high-level intent of the current work",
      "current_step": "what the agent was doing right before dying",
      "release":      "last release the agent shipped",
      "notes":        ["chronological observations, newest last"],
      "updated_at":   "ISO-8601 UTC timestamp"
    }

Deliberately kept dead-simple:
  - stdlib only (no schema library, no lockfile)
  - single-writer assumption (the current agent)
  - overwrite semantics for write_checkpoint (agent owns the state)
  - append_note is the only compositional op (survives partial writes)

If the schema grows past a screenful, split into a separate module.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _session_path() -> Path:
    override = os.environ.get("ARENA_AGENT_SESSION_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".arena" / "agent_session.json"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_checkpoint(payload: dict[str, Any]) -> Path:
    """Overwrite the checkpoint with `payload`, auto-stamping updated_at.

    Callers pass the agent's current intent. Any fields not present are
    left unset (the next reader can fall back to their own defaults).
    """
    if not isinstance(payload, dict):
        raise TypeError("checkpoint payload must be a dict")
    data = dict(payload)
    data["updated_at"] = _now_utc_iso()
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic on POSIX; near-atomic on Windows
    return path


def read_checkpoint() -> dict[str, Any] | None:
    """Return the last checkpoint or None if there is no file / it's
    unparseable. Never raises — a corrupt file is treated as "no
    checkpoint" so the next agent can just start fresh."""
    path = _session_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def append_note(note: str) -> None:
    """Append a chronological observation to the current checkpoint.

    If no checkpoint exists yet, creates one with just the note. This
    is the safe primitive for "I just tried X, here's what I saw" —
    each note is a durable line without overwriting the goal.
    """
    existing = read_checkpoint() or {}
    notes = list(existing.get("notes") or [])
    notes.append(str(note))
    existing["notes"] = notes
    write_checkpoint(existing)


def clear_checkpoint() -> bool:
    """Delete the checkpoint. Returns True if a file was removed."""
    path = _session_path()
    if path.exists():
        path.unlink()
        return True
    return False


__all__ = ["_session_path", "write_checkpoint", "read_checkpoint",
           "append_note", "clear_checkpoint"]
