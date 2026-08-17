"""T63: recall must return only facts with positive lexical relevance."""
from __future__ import annotations

import pytest

from arena.memory.recall import recall

FACTS = [
    {"key": "apple", "value": "red apple fruit", "tags": ["food"]},
    {"key": "database", "value": "postgres index tuning", "tags": ["sql"]},
]


@pytest.mark.parametrize("query", ["quantum_banana_xyzzy", "zzzzzzzz", "яблоко"])
def test_unmatched_query_returns_honest_empty_result(query: str) -> None:
    result = recall(query, facts=FACTS, top=5)
    assert result == {"ok": True, "query": query, "count": 0, "facts": []}


@pytest.mark.parametrize("query", ["", "   ", "!!!!"])
def test_query_without_tokens_does_not_return_recent_zero_score_facts(query: str) -> None:
    result = recall(query, facts=FACTS, top=5)
    assert result == {"ok": True, "query": query, "count": 0, "facts": []}


def test_positive_hits_are_ranked_and_zero_score_facts_are_removed() -> None:
    result = recall("apple food", facts=FACTS, top=5)
    assert result["count"] == 1
    assert [item["fact"]["key"] for item in result["facts"]] == ["apple"]
    assert result["facts"][0]["score"] > 0
    assert all(item["score"] > 0 for item in result["facts"])


def test_top_limit_applies_after_relevance_filter() -> None:
    facts = [
        {"key": "first", "value": "alpha alpha"},
        {"key": "second", "value": "alpha"},
        {"key": "noise", "value": "unrelated"},
    ]
    result = recall("alpha", facts=facts, top=1)
    assert result["count"] == 1
    assert result["facts"][0]["fact"]["key"] == "first"
    assert result["facts"][0]["score"] == 0.4


def test_score_rounding_and_unicode_tokens_are_contractual() -> None:
    rounded = recall("alpha", facts=[{"a": "alpha beta"}], top=5)
    assert rounded["facts"][0]["score"] == 0.333333
    unicode_hit = recall("яблоко", facts=[{"value": "красное яблоко"}], top=5)
    assert unicode_hit["count"] == 1
    assert unicode_hit["facts"][0]["score"] > 0


def test_empty_fact_text_and_empty_store_remain_empty() -> None:
    punctuation = [
        {"!!!": "???"},
        {"key": "later", "value": "alpha"},
    ]
    result = recall("alpha", facts=punctuation, top=5)
    assert result["count"] == 1
    assert result["facts"][0]["fact"]["key"] == "later"
    assert recall("alpha", facts=[], top=5) == {
        "ok": True, "query": "alpha", "count": 0, "facts": [],
    }
