#!/usr/bin/env python3
"""memory_recall.py — авто-извлечение релевантных фактов и сессий из памяти агента.

Когда новая задача приходит в чат, мы хотим автоматически найти прошлые факты,
снимки и summary, которые упоминают похожие слова. Это снимает нагрузку с LLM
(он не должен помнить всё сам).

Источники:
  - ~/arena-bridge/memory/facts.jsonl    (key/value/tags)
  - ~/arena-bridge/memory/sessions/*.jsonl (last 20)
  - ~/arena-bridge/reports/snapshots/*.md  (last 5)
  - ~/arena-bridge/subagents/*/summary.json

Команды:
  recall <query> [--top N]      — топ N релевантных воспоминаний (JSON)
  digest                        — единый markdown digest из памяти
"""
from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path
from collections import Counter

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
MEM  = ROOT / "memory"
RPT  = ROOT / "reports"
SUB  = ROOT / "subagents"


def tokenize(s: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[a-zа-яё0-9_.\-/]{2,}", s, flags=re.I)]


def score(text: str, q_tokens: list[str]) -> int:
    """Простой TF-скор: сумма количества вхождений токенов запроса."""
    if not text or not q_tokens: return 0
    counts = Counter(tokenize(text))
    return sum(counts.get(t, 0) for t in q_tokens)


def recall_facts(q_tokens: list[str], top: int) -> list[dict]:
    """Возврат top фактов из facts.jsonl с ненулевым score."""
    p = MEM / "facts.jsonl"
    if not p.exists(): return []
    items = []
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line: continue
        sc = score(line, q_tokens)
        if sc > 0:
            items.append({"score": sc, "text": line[:500]})
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:top]


def recall_snapshots(q_tokens: list[str], top: int) -> list[dict]:
    snap_dir = RPT / "snapshots"
    if not snap_dir.exists(): return []
    items = []
    for f in sorted(snap_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        try:
            text = f.read_text(errors="replace")
            sc = score(text, q_tokens)
            if sc > 0:
                items.append({"score": sc, "file": f.name,
                              "preview": text[:300]})
        except Exception: pass
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:top]


def recall_subagents(q_tokens: list[str], top: int) -> list[dict]:
    if not SUB.exists(): return []
    items = []
    for d in SUB.iterdir():
        s = d / "summary.json"
        if not s.exists(): continue
        try:
            data = json.loads(s.read_text())
            blob = json.dumps(data, ensure_ascii=False)
            sc = score(blob, q_tokens)
            if sc > 0:
                items.append({"score": sc, "id": data.get("id"),
                              "name": data.get("name"), "status": data.get("status"),
                              "stdout_tail": (data.get("stdout_tail") or "")[:300]})
        except Exception: pass
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:top]


def recall_sessions(q_tokens: list[str], top: int) -> list[dict]:
    sd = MEM / "sessions"
    if not sd.exists(): return []
    items = []
    for f in sorted(sd.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        try:
            text = f.read_text(errors="replace")
            sc = score(text, q_tokens)
            if sc > 0:
                items.append({"score": sc, "file": f.name, "preview": text[:300]})
        except Exception: pass
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:top]


def cmd_recall(args) -> int:
    q = tokenize(args.query)
    out = {
        "query": args.query,
        "tokens": q,
        "facts": recall_facts(q, args.top),
        "snapshots": recall_snapshots(q, args.top),
        "subagents": recall_subagents(q, args.top),
        "sessions": recall_sessions(q, args.top),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_digest(_args) -> int:
    """Сводный markdown для подкладывания нового LLM в начало чата."""
    lines = ["# Memory digest", ""]
    # Последние 10 фактов
    p = MEM / "facts.jsonl"
    if p.exists():
        facts = [l for l in p.read_text(errors="replace").splitlines() if l.strip()][-10:]
        lines.append("## Recent facts (last 10)")
        for f in facts: lines.append(f"- {f[:200]}")
        lines.append("")
    # Последние 3 snapshot
    snap_dir = RPT / "snapshots"
    if snap_dir.exists():
        snaps = sorted(snap_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
        lines.append("## Recent snapshots")
        for s in snaps: lines.append(f"- {s.name}")
        lines.append("")
    # Последние 5 subagents
    if SUB.exists():
        subs = sorted(SUB.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        lines.append("## Recent subagents")
        for d in subs:
            mp = d / "meta.json"
            if mp.exists():
                try:
                    m = json.loads(mp.read_text())
                    lines.append(f"- {m.get('id')} [{m.get('status')}] {m.get('name')}: {m.get('cmd','')[:60]}")
                except Exception: pass
        lines.append("")
    print("\n".join(lines))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="memory_recall")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recall"); r.add_argument("query"); r.add_argument("--top", type=int, default=5); r.set_defaults(func=cmd_recall)
    sub.add_parser("digest").set_defaults(func=cmd_digest)
    args = ap.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
