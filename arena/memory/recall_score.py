"""Memory recall tokenization/scoring."""
from __future__ import annotations

from arena.memory.recall_paths import *  # noqa: F401,F403

def tokenize(s: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[a-zа-яё0-9_.\-/]{2,}", s, flags=re.I)]

def score(text: str, q_tokens: list[str]) -> int:
    """Простой TF-скор: сумма количества вхождений токенов запроса."""
    if not text or not q_tokens: return 0
    counts = Counter(tokenize(text))
    return sum(counts.get(t, 0) for t in q_tokens)
