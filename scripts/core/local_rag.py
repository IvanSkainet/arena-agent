#!/usr/bin/env python3
"""
Local RAG (Semantic Search Proxy) 
A lightweight wrapper that allows querying codebase or text via fast FTS5 SQLite index.
If no index exists, it creates one by scanning text files.
"""
from __future__ import annotations
import os, sys, sqlite3, glob, re
from pathlib import Path

DB_PATH = os.path.expanduser("~/.arena-snapshots/rag_index.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # Adding timeout=30 to handle "database is locked" errors automatically
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS codebase USING fts5(filepath, content, tokenize='trigram');")
    conn.commit()
    return conn

def build_index(cwd: str):
    conn = init_db()
    
    try:
        conn.execute("DELETE FROM codebase;") # clear old
    except sqlite3.OperationalError as e:
        print(f"Error clearing old index (might be locked): {e}")
        # Force unlocking by reopening with isolation_level=None (autocommit)
        conn.close()
        conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=30.0)
        conn.execute("DELETE FROM codebase;")
    
    print(f"Indexing {cwd}...")
    count = 0
    # Avoid scanning the entire home directory if user accidentally runs it from ~
    # We restrict the scan to the arena-bridge dir or the specific project dir requested.
    scan_dir = cwd
    if os.path.abspath(cwd) == os.path.expanduser("~"):
        scan_dir = os.path.join(cwd, "arena-bridge")
        print(f"Warning: Root directory scan detected. Restricted to {scan_dir} to save time.")
        if not os.path.exists(scan_dir):
            print("arena-bridge not found in home. Please run inside a specific project.")
            sys.exit(1)
            
    for root, dirs, files in os.walk(scan_dir):
        # Exclude common heavy directories and hidden ones
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'build', 'dist', 'coverage', 'venv', '.venv')]
        for f in files:
            if f.endswith(('.py', '.js', '.ts', '.html', '.css', '.md', '.json', '.sh', '.ps1', '.txt')):
                fpath = os.path.join(root, f)
                # Ensure we aren't indexing the DB itself or huge files
                if fpath == DB_PATH or os.path.getsize(fpath) > 1024 * 500: # 500kb max per file
                    continue
                try:
                    with open(fpath, 'r', encoding='utf-8') as file:
                        content = file.read()
                        conn.execute("INSERT INTO codebase (filepath, content) VALUES (?, ?)", (fpath, content))
                        count += 1
                except Exception:
                    pass
                    
    conn.commit()
    conn.close()
    print(f"Indexed {count} text files into Local RAG.")

def search(query: str):
    if not os.path.exists(DB_PATH):
        print("Index not found. Run 'agentctl rag index' first.")
        return
        
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cur = conn.cursor()
    # Simple MATCH query using FTS5 trigram tokenizer.
    # We must sanitize the query for FTS5 parser: wrap in double quotes to prevent syntax errors with single quotes.
    safe_query = '"' + query.replace('"', '""') + '"'
    
    try:
        cur.execute("SELECT filepath, snippet(codebase, -1, '>>>', '<<<', '...', 10) FROM codebase WHERE codebase MATCH ? ORDER BY rank LIMIT 8", (safe_query,))
        results = cur.fetchall()
        
        if not results:
            print(f"No results found for {safe_query}")
            conn.close()
            return
            
        print(f"Top results for '{query}':\n")
        for filepath, snippet in results:
            print(f"📄 {filepath}")
            print(f"   {snippet}\n")
    except sqlite3.OperationalError as e:
        print(f"Search error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: local_rag.py [index|search] [query]")
        sys.exit(1)
        
    cmd = sys.argv[1]
    if cmd == "index":
        build_index(os.getcwd())
    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Please provide a search query.")
            sys.exit(1)
        search(" ".join(sys.argv[2:]))
