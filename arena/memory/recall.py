"""In-memory fact recall and digest helpers."""
from __future__ import annotations

import json
from typing import Any, Callable

from arena.memory.recall_relevance import recall_relevant


def recall(query: str, *, facts: list[dict[str, Any]], top: int) -> dict[str, Any]:
    return recall_relevant(query, facts=facts, top=top)


def recall_digest(*, facts: list[dict[str, Any]], audit_lines: list[str], utc_now_fn: Callable[[], str]) -> dict[str, Any]:
    lines: list[str] = ["# Memory Digest", f"Generated: {utc_now_fn()}\n"]
    recent_facts = facts[-50:]
    lines.append(f"## Recent Facts ({len(recent_facts)} of {len(facts)})\n")
    for fact in recent_facts:
        key = fact.get("key", "unknown")
        value = str(fact.get("value", ""))[:200]
        ts = fact.get("timestamp", "")
        tags = fact.get("tags", [])
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- **{key}**{tag_str}: {value} _({ts})_")
    lines.append("")

    events = []
    for line in audit_lines:
        try:
            events.append(json.loads(line))
        except Exception:
            pass
    lines.append(f"## Recent Audit Events ({len(events)})\n")
    for ev in events:
        ev_type = ev.get("type", "unknown")
        ts = ev.get("ts", "")
        detail = ""
        if "cmd" in ev:
            detail = f": `{ev['cmd'][:100]}`"
        elif "path" in ev:
            detail = f": {ev['path']}"
        elif "error" in ev:
            detail = f": {str(ev['error'])[:100]}"
        lines.append(f"- [{ev_type}] _{ts}_{detail}")
    lines.append("")

    return {"ok": True, "digest": "\n".join(lines), "fact_count": len(recent_facts), "event_count": len(events)}
