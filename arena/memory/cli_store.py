"""Memory CLI storage helpers."""
from __future__ import annotations

from arena.memory.cli_paths import *  # noqa: F401,F403

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
