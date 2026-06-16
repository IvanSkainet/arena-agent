"""In-memory fact recall and digest helpers."""
from __future__ import annotations

import collections
import json
import re
from typing import Any, Callable


def recall(query: str, *, facts: list[dict[str, Any]], top: int) -> dict[str, Any]:
    if not facts:
        return {"ok": True, "query": query, "count": 0, "facts": []}
    query_terms = set(re.findall(r'\w+', query.lower()))
    if not query_terms:
        return {"ok": True, "query": query, "count": min(top, len(facts)), "facts": [{"fact": f, "score": 0.0} for f in facts[-top:]]}
    scored = []
    for fact in facts:
        fact_text = json.dumps(fact, ensure_ascii=False).lower()
        fact_terms = re.findall(r'\w+', fact_text)
        if not fact_terms:
            scored.append({"fact": fact, "score": 0.0})
            continue
        term_counts = collections.Counter(fact_terms)
        score = 0.0
        for qt in query_terms:
            if qt in term_counts:
                score += term_counts[qt] / len(fact_terms)
        scored.append({"fact": fact, "score": round(score, 6)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    non_zero = [s for s in scored if s["score"] > 0]
    result_facts = non_zero[:top] if non_zero else scored[:top]
    return {"ok": True, "query": query, "count": len(result_facts), "facts": result_facts}


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
