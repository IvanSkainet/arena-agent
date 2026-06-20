"""Memory recall data sources."""
from __future__ import annotations

from arena.memory.profiles import DEFAULT_MEMORY_PROFILE, normalize_memory_profile_filter
from arena.memory.recall_paths import *  # noqa: F401,F403
from arena.memory.recall_score import score

def recall_facts(q_tokens: list[str], top: int, profile: str | None = DEFAULT_MEMORY_PROFILE) -> list[dict]:
    """Возврат top фактов из facts.db с ненулевым score."""
    p = get_mem_dir() / "facts.db"
    if not p.exists(): return []
    items = []
    profile_filter = None if profile is None else normalize_memory_profile_filter(profile)
    try:
        with sqlite3.connect(p) as conn:
            conn.row_factory = sqlite3.Row
            cols = [row[1] for row in conn.execute("PRAGMA table_info(memory_facts)").fetchall()]
            if "profile" in cols:
                if profile_filter is None:
                    cursor = conn.execute("SELECT profile, key, value, tags, timestamp FROM memory_facts")
                else:
                    cursor = conn.execute("SELECT profile, key, value, tags, timestamp FROM memory_facts WHERE profile = ?", (profile_filter,))
            else:
                cursor = conn.execute("SELECT key, value, tags, timestamp FROM memory_facts")
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
                    "profile": r['profile'] if 'profile' in r.keys() else DEFAULT_MEMORY_PROFILE,
                    "key": key,
                    "value": value,
                    "tags": tags_list
                }
                line = json.dumps(fact_obj, ensure_ascii=False)
                sc = score(line, q_tokens)
                if sc > 0:
                    items.append({"score": sc, "text": line[:500]})
    except Exception as e:
        print(f"error querying database in recall_facts: {e}", file=sys.stderr)
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:top]

def recall_snapshots(q_tokens: list[str], top: int) -> list[dict]:
    snap_dir = get_rpt_dir() / "snapshots"
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
    sub_dir = get_sub_dir()
    if not sub_dir.exists(): return []
    items = []
    for d in sub_dir.iterdir():
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
    sd = get_mem_dir() / "sessions"
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
