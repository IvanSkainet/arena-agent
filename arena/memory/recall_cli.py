"""CLI dispatcher for bin/memory_recall.py."""
from __future__ import annotations

from arena.memory.recall_sources import *  # noqa: F401,F403
from arena.memory.recall_score import tokenize

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
    # Последние 10 фактов из SQLite
    p = get_mem_dir() / "facts.db"
    if p.exists():
        lines.append("## Recent facts (last 10)")
        try:
            with sqlite3.connect(p) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT key, value, tags, timestamp FROM memory_facts ORDER BY timestamp DESC LIMIT 10")
                facts = []
                for r in cursor:
                    key = r['key'] or ""
                    value = r['value'] or ""
                    try:
                        tags_list = json.loads(r['tags']) if r['tags'] else []
                    except Exception:
                        tags_list = []
                    fact_obj = {
                        "ts": r['timestamp'],
                        "type": "fact",
                        "key": key,
                        "value": value,
                        "tags": tags_list
                    }
                    facts.append(json.dumps(fact_obj, ensure_ascii=False))
                facts.reverse()
                for f in facts: lines.append(f"- {f[:200]}")
        except Exception as e:
            lines.append(f"Error reading facts: {e}")
        lines.append("")
    # Последние 3 snapshot
    snap_dir = get_rpt_dir() / "snapshots"
    if snap_dir.exists():
        snaps = sorted(snap_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
        lines.append("## Recent snapshots")
        for s in snaps: lines.append(f"- {s.name}")
        lines.append("")
    # Последние 5 subagents
    sub_dir = get_sub_dir()
    if sub_dir.exists():
        subs = sorted(sub_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
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
