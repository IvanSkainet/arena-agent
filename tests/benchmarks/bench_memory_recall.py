"""Benchmarks for memory recall tokenisation and scoring.

``arena.memory.recall_score`` is the inner loop of every ``/v1/memory``
recall: the query is tokenised once, then every candidate record is
tokenised and scored against it. The cost therefore scales with the size
of the corpus, not with the size of the query, which is why the corpus
below is a few dozen records rather than one.

The token pattern is deliberately bilingual (``[a-zа-яё0-9_.\\-/]``) --
this project's memory holds Russian notes alongside English ones -- so a
Cyrillic corpus is measured too. A regex that is fast on ASCII and slow on
Cyrillic would otherwise regress unnoticed.
"""
from __future__ import annotations

from arena.memory.recall_score import score, tokenize

ENGLISH_RECORDS = [
    "Bridge restart loop traced to the websocket reconnect backoff in "
    "arena/relay/ws_client.py; the retry timer was never cancelled.",
    "Mission m-4711 failed on step 2: npm run build exited 137 (out of "
    "memory) on the dashboard bundle.",
    "Token rotation now unregisters the previous literal from the redaction "
    "snapshot before publishing the new one.",
    "Desktop capture on Wayland needs the portal backend; the X11 path "
    "returns a black frame under GNOME 46.",
    "Rate limiter v2 stopped recording rejected requests, which was making "
    "the window self-sustaining for a retrying client.",
    "Skill install verifies the git source signature before the runner is "
    "allowed to execute anything from the checkout.",
] * 6

RUSSIAN_RECORDS = [
    "Мост перезапускается по кругу: таймер повторного подключения websocket "
    "не отменялся при закрытии сессии.",
    "Миссия m-4711 упала на шаге 2 — сборка дашборда завершилась кодом 137.",
    "Ротация токена теперь снимает регистрацию старого литерала до публикации "
    "нового снимка редакции.",
    "Захват экрана в Wayland требует portal-бэкенда, путь X11 отдаёт чёрный кадр.",
] * 6

QUERY = "websocket reconnect backoff retry timer bridge restart"
RUSSIAN_QUERY = "перезапуск моста websocket таймер подключения"

LONG_DOCUMENT = " ".join(ENGLISH_RECORDS)


def test_tokenize_long_document(benchmark) -> None:
    """One pass of the token regex over a few kilobytes of prose."""
    assert len(benchmark(tokenize, LONG_DOCUMENT)) > 100


def test_tokenize_short_record(benchmark) -> None:
    """The per-record cost, which is what the corpus size multiplies."""
    assert benchmark(tokenize, ENGLISH_RECORDS[0])


def test_score_english_corpus(benchmark) -> None:
    """Full recall pass: tokenise the query once, score every record."""
    q_tokens = tokenize(QUERY)

    def score_all() -> int:
        return sum(score(record, q_tokens) for record in ENGLISH_RECORDS)

    assert benchmark(score_all) > 0


def test_score_cyrillic_corpus(benchmark) -> None:
    """The same pass over Cyrillic text, where the pattern behaves differently."""
    q_tokens = tokenize(RUSSIAN_QUERY)

    def score_all() -> int:
        return sum(score(record, q_tokens) for record in RUSSIAN_RECORDS)

    assert benchmark(score_all) > 0


def test_score_no_match(benchmark) -> None:
    """A query that matches nothing still tokenises every record."""
    q_tokens = tokenize("zzzz qqqq wwww")

    def score_all() -> int:
        return sum(score(record, q_tokens) for record in ENGLISH_RECORDS)

    assert benchmark(score_all) == 0
