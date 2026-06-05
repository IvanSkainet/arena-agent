#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import sqlite3
from pathlib import Path

def get_mem_dir() -> Path:
    root = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
    return root / "memory"

def get_db_path() -> Path:
    return get_mem_dir() / "facts.db"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def append(obj: dict) -> None:
    mem_dir = get_mem_dir()
    mem_dir.mkdir(parents=True, exist_ok=True)
    db_path = get_db_path()
    
    with sqlite3.connect(db_path) as conn:
        # Ensure schema matches unified_bridge.py exactly
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
        
        key = obj.get("key", "")
        value = obj.get("value", "")
        tags = json.dumps(obj.get("tags", []))
        timestamp = obj.get("ts", "")
        
        conn.execute("""
        INSERT INTO memory_facts (key, value, tags, timestamp)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            tags=excluded.tags,
            timestamp=excluded.timestamp
        """, (key, value, tags, timestamp))
        conn.commit()
        
    try:
        os.chmod(db_path, 0o600)
    except Exception:
        pass


def _expand_tags(tokens: list[str]) -> list[str]:
    tags: list[str] = []
    for token in tokens:
        for part in str(token).split(","):
            tag = part.strip()
            if tag:
                tags.append(tag)
    return tags


def _split_remember_rest(rest: list[str]) -> tuple[list[str], list[str]]:
    """Parse flexible remember syntax.

    Supported forms:
      memory-remember KEY value words --tags tag1 tag2
      memory-remember KEY value words --tags=tag1,tag2
      memory-remember KEY --tags tag1 tag2 -- value words
      memory-remember KEY value words

    The old argparse REMAINDER parser swallowed --tags into value.  We parse the
    tail manually so --tags works predictably and remains backwards-compatible
    for calls that do not use tags.
    """
    rest = list(rest or [])
    tag_idx = None
    tag_inline: str | None = None
    for i, token in enumerate(rest):
        if token == "--tags":
            tag_idx = i
            break
        if token.startswith("--tags="):
            tag_idx = i
            tag_inline = token.split("=", 1)[1]
            break

    if tag_idx is None:
        return rest, []

    before = rest[:tag_idx]
    after = rest[tag_idx + 1 :]
    if tag_inline is not None:
        after = [tag_inline] + after

    # Preferred form: value first, tags last.
    if before:
        return before, _expand_tags(after)

    # Alternate form: tags first, explicit -- separator, then value.
    if "--" in after:
        sep = after.index("--")
        return after[sep + 1 :], _expand_tags(after[:sep])

    raise ValueError(
        "when --tags is placed before value, separate tags and value with '--'; "
        "example: memory-remember key --tags todo recovery -- value words"
    )


def remember(args: argparse.Namespace) -> int:
    value_tokens, tags = _split_remember_rest(args.rest)
    if not value_tokens:
        raise ValueError("value is required")
    append({"ts": now(), "type": "fact", "key": args.key,
            "value": " ".join(value_tokens), "tags": tags})
    print(f"remembered: {args.key} [{','.join(tags) or '-'}]")
    return 0


def recall(args: argparse.Namespace) -> int:
    db_path = get_db_path()
    if not db_path.exists():
        print("no facts")
        return 0
    q = (args.query or "").lower()
    rows: list[dict] = []
    
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC")
            for r in cursor:
                key = r['key'] or ""
                value = r['value'] or ""
                try:
                    tags_list = json.loads(r['tags']) if r['tags'] else []
                except Exception:
                    tags_list = []
                
                obj = {
                    "ts": r['timestamp'],
                    "key": key,
                    "value": value,
                    "tags": tags_list
                }
                
                hay = (
                    str(key) + " " +
                    str(value) + " " +
                    json.dumps(tags_list, ensure_ascii=False)
                ).lower()
                if q and q not in hay:
                    continue
                rows.append(obj)
    except Exception as e:
        print(f"error querying database: {e}", file=sys.stderr)
        return 1

    for obj in rows[-args.limit:]:
        tags = obj.get("tags") or []
        suffix = f" --tags {','.join(tags)}" if tags else ""
        print(f"[{obj.get('ts')}] {obj.get('key')}: {obj.get('value')}{suffix}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("remember")
    s.add_argument("key")
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s.set_defaults(func=remember)

    s = sub.add_parser("recall")
    s.add_argument("query", nargs="?")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=recall)

    args = p.parse_args()
    try:
        return int(args.func(args) or 0)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
