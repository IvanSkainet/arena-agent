"""Memory CLI commands."""
from __future__ import annotations

from arena.memory.cli_parser import _split_remember_rest
from arena.memory.cli_paths import *  # noqa: F401,F403
from arena.memory.cli_store import append

def remember(args: argparse.Namespace) -> int:
    value_tokens, tags = _split_remember_rest(args.rest)
    if not value_tokens:
        raise ValueError("value is required")
    append({"ts": now(), "type": "fact", "profile": getattr(args, "profile", "default"), "key": args.key,
            "value": " ".join(value_tokens), "tags": tags})
    print(f"remembered: {args.key} [{','.join(tags) or '-'}] profile={getattr(args, 'profile', 'default')}")
    return 0

def recall(args: argparse.Namespace) -> int:
    db_path = get_db_path()
    if not db_path.exists():
        print("no facts")
        return 0
    q = (args.query or "").lower()
    rows: list[dict] = []
    
    profile = getattr(args, "profile", "default")
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cols = [row[1] for row in conn.execute("PRAGMA table_info(memory_facts)").fetchall()]
            if "profile" in cols and profile not in ("all", "*"):
                cursor = conn.execute("SELECT profile, key, value, tags, timestamp FROM memory_facts WHERE profile = ? ORDER BY timestamp ASC", (profile,))
            else:
                cursor = conn.execute("SELECT profile, key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC" if "profile" in cols else "SELECT key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC")
            for r in cursor:
                key = r['key'] or ""
                value = r['value'] or ""
                try:
                    tags_list = json.loads(r['tags']) if r['tags'] else []
                except Exception:
                    tags_list = []
                
                obj = {
                    "ts": r['timestamp'],
                    "profile": r['profile'] if 'profile' in r.keys() else 'default',
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
