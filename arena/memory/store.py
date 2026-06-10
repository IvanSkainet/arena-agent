"""SQLite-backed memory store and recall helpers."""
from __future__ import annotations

import collections
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable


def init_memory_db(*, db_path: Path, jsonl_path: Path, log_error: Callable[..., None] | None = None) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS memory_facts (
            key TEXT PRIMARY KEY,
            value TEXT,
            tags TEXT,
            timestamp TEXT
        );
        ''')
        conn.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            key, value, tags, content=memory_facts, content_rowid=rowid, tokenize="trigram"
        );
        ''')
        conn.executescript('''
        CREATE TRIGGER IF NOT EXISTS memory_facts_ai AFTER INSERT ON memory_facts BEGIN
            INSERT INTO memory_fts(rowid, key, value, tags) VALUES (new.rowid, new.key, new.value, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_facts_ad AFTER DELETE ON memory_facts BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, key, value, tags) VALUES ('delete', old.rowid, old.key, old.value, old.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_facts_au AFTER UPDATE ON memory_facts BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, key, value, tags) VALUES ('delete', old.rowid, old.key, old.value, old.tags);
            INSERT INTO memory_fts(rowid, key, value, tags) VALUES (new.rowid, new.key, new.value, new.tags);
        END;
        ''')

    if jsonl_path.exists():
        migrated_path = jsonl_path.with_suffix(".jsonl.migrated")
        if not migrated_path.exists():
            with sqlite3.connect(db_path) as conn:
                try:
                    with open(jsonl_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                item = json.loads(line)
                                key = item.get("key", "")
                                value = item.get("value", "")
                                tags = json.dumps(item.get("tags", []))
                                timestamp = item.get("timestamp", "")
                                conn.execute("""
                                INSERT INTO memory_facts (key, value, tags, timestamp)
                                VALUES (?, ?, ?, ?)
                                ON CONFLICT(key) DO UPDATE SET
                                    value=excluded.value,
                                    tags=excluded.tags,
                                    timestamp=excluded.timestamp
                                """, (key, value, tags, timestamp))
                            except json.JSONDecodeError:
                                pass
                    conn.commit()
                except Exception as e:
                    if log_error:
                        log_error("[Memory] Failed to migrate facts: %s", e)
            try:
                jsonl_path.rename(migrated_path)
            except OSError:
                pass


def _row_to_fact(row) -> dict[str, Any]:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except Exception:
        tags = []
    return {"key": row["key"], "value": row["value"], "tags": tags, "timestamp": row["timestamp"]}


def load_facts(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC").fetchall()
        return [_row_to_fact(row) for row in rows]


def search_facts_paged(db_path: Path, q: str = "", offset: int = 0, limit: int = 100, log_error: Callable[..., None] | None = None) -> tuple[int, list[dict[str, Any]]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if q:
            safe_q = '"' + q.replace('"', '""') + '"'
            try:
                total = conn.execute("SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH ?", (safe_q,)).fetchone()[0]
                rows = conn.execute('''
                    SELECT m.key, m.value, m.tags, m.timestamp
                    FROM memory_facts m
                    JOIN memory_fts f ON m.rowid = f.rowid
                    WHERE memory_fts MATCH ?
                    ORDER BY m.timestamp ASC
                    LIMIT ? OFFSET ?
                ''', (safe_q, limit, offset)).fetchall()
            except sqlite3.OperationalError as e:
                if log_error:
                    log_error("[Memory] SQLite FTS query error: %s", e)
                return 0, []
        else:
            total = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
            rows = conn.execute("SELECT key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return total, [_row_to_fact(row) for row in rows]


def write_fact(db_path: Path, entry: dict[str, Any]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
        INSERT INTO memory_facts (key, value, tags, timestamp)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            tags=excluded.tags,
            timestamp=excluded.timestamp
        ''', (entry.get("key", ""), entry.get("value", ""), json.dumps(entry.get("tags", [])), entry.get("timestamp", "")))
        conn.commit()


def delete_fact(db_path: Path, key: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM memory_facts WHERE key = ?", (key,))
        conn.commit()
        return cur.rowcount > 0


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
    result_facts = (non_zero[:top] if non_zero else scored[:top])
    return {"ok": True, "query": query, "count": len(result_facts), "facts": result_facts}


def recall_digest(*, facts: list[dict[str, Any]], audit_lines: list[str], utc_now_fn: Callable[[], str]) -> dict[str, Any]:
    lines: list[str] = []
    lines.append("# Memory Digest")
    lines.append(f"Generated: {utc_now_fn()}\n")
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
    digest = "\n".join(lines)
    return {"ok": True, "digest": digest, "fact_count": len(recent_facts), "event_count": len(events)}
