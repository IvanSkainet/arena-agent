"""In-memory fact recall and digest helpers."""
from __future__ import annotations

import json
from typing import Any, Callable

from arena.memory.recall_relevance import recall_relevant


def recall(query: str, *, facts: list[dict[str, Any]], top: int) -> dict[str, Any]:
    return recall_relevant(query, facts=facts, top=top)


def _fact_line(fact: dict[str, Any]) -> str:
    """One "- **key** [tags]: value _(ts)_" line.

    Every field goes through `str`, because the API stores whatever JSON a
    caller sends: `{"tags": [null]}` was accepted on the way in and then
    `", ".join` raised TypeError on the way out, so one fact took the whole
    digest down for every later reader (#270, found by the fuzzing gate).
    """
    tags = fact.get("tags") or []
    tags = [str(tag) for tag in tags] if isinstance(tags, list) else []
    tag_str = f" [{', '.join(tags)}]" if tags else ""
    key = fact.get("key", "unknown")
    value = str(fact.get("value", ""))[:200]
    return f"- **{key}**{tag_str}: {value} _({fact.get('timestamp', '')})_"


def _event_line(event: dict[str, Any]) -> str:
    """One "- [type] _ts_: detail" line, with the same rule about types."""
    detail = ""
    if "cmd" in event:
        detail = f": `{str(event['cmd'])[:100]}`"
    elif "path" in event:
        detail = f": {str(event['path'])[:200]}"
    elif "error" in event:
        detail = f": {str(event['error'])[:100]}"
    return f"- [{event.get('type', 'unknown')}] _{event.get('ts', '')}_{detail}"


def _parsed_events(audit_lines: list[str]) -> list[dict[str, Any]]:
    """The audit lines that are JSON objects; the rest are skipped.

    A line that parses to a bare number or string is not an event, and
    `.get` on it is the TypeError this function exists to avoid.
    """
    events = []
    for line in audit_lines:
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def recall_digest(*, facts: list[dict[str, Any]], audit_lines: list[str], utc_now_fn: Callable[[], str]) -> dict[str, Any]:
    lines: list[str] = ["# Memory Digest", f"Generated: {utc_now_fn()}\n"]
    recent_facts = facts[-50:]
    lines.append(f"## Recent Facts ({len(recent_facts)} of {len(facts)})\n")
    lines += [_fact_line(fact) for fact in recent_facts if isinstance(fact, dict)]
    lines.append("")

    events = _parsed_events(audit_lines)
    lines.append(f"## Recent Audit Events ({len(events)})\n")
    lines += [_event_line(event) for event in events]
    lines.append("")

    return {"ok": True, "digest": "\n".join(lines), "fact_count": len(recent_facts), "event_count": len(events)}
