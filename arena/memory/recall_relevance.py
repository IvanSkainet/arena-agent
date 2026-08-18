"""Positive-score lexical relevance for in-memory fact recall."""
from __future__ import annotations

import collections
import json
import re
from typing import Any


def recall_relevant(
    query: str,
    *,
    facts: list[dict[str, Any]],
    top: int,
) -> dict[str, Any]:
    """Return at most ``top`` facts sharing at least one query token."""
    if not facts:
        return {"ok": True, "query": query, "count": 0, "facts": []}
    query_terms = set(re.findall(r"\w+", query.lower()))
    if not query_terms:
        return {"ok": True, "query": query, "count": 0, "facts": []}
    scored: list[dict[str, Any]] = []
    for fact in facts:
        fact_terms = re.findall(
            r"\w+", json.dumps(fact, ensure_ascii=False).lower()
        )
        if not fact_terms:
            continue
        term_counts = collections.Counter(fact_terms)
        score = sum(
            term_counts[term] / len(fact_terms)
            for term in query_terms if term in term_counts
        )
        if score > 0:
            scored.append({"fact": fact, "score": round(score, 6)})
    scored.sort(key=lambda item: item["score"], reverse=True)
    selected = scored[:top]
    return {
        "ok": True,
        "query": query,
        "count": len(selected),
        "facts": selected,
    }
