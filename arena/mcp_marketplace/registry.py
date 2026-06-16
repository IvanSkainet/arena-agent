"""MCP marketplace implementation."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
MCP_DIR = ROOT / "mcp"
CONFIG = MCP_DIR / "mcp.json"
REGISTRY = MCP_DIR / "registry.json"

DEFAULT_REGISTRY = {
    "filesystem": {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home())],
        "description": "File system access (read/write/list) inside given root.",
        "tags": ["fs", "official"],
    },
    "fetch": {
        "command": "uvx", "args": ["-q", "mcp-server-fetch"],
        "description": "HTTP fetch tool (server-side).",
        "tags": ["web", "official"],
    },
    "sqlite": {
        "command": "uvx", "args": ["-q", "mcp-server-sqlite", "--db-path", str(ROOT / "memory" / "facts.db")],
        "description": "SQLite query tool over local DB.",
        "tags": ["db", "official"],
    },
    "git": {
        "command": "uvx", "args": ["-q", "mcp-server-git", "--repository", str(Path.home())],
        "description": "Git operations (status, log, diff, branch).",
        "tags": ["git", "official"],
    },
    "memory": {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"],
        "description": "Knowledge-graph long-term memory.",
        "tags": ["memory", "official"],
    },
    "time": {
        "command": "uvx", "args": ["-q", "mcp-server-time"],
        "description": "Time, timezones, date math.",
        "tags": ["util", "official"],
    },
    "puppeteer": {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "description": "Browser automation via Puppeteer (chromium needed).",
        "tags": ["browser"],
    },
    "everything": {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"],
        "description": "Reference server with all MCP feature types.",
        "tags": ["test", "official"],
    },
    "arena-stream": {
        "command": "echo", "args": ["arena-mcp-stream runs on http://127.0.0.1:8767/mcp"],
        "description": "Local arena-mcp-stream service (20 tools).",
        "tags": ["local", "arena"],
    },
}

def _ensure():
    MCP_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps({"mcpServers": {}}, indent=2))
    if not REGISTRY.exists():
        REGISTRY.write_text(json.dumps(DEFAULT_REGISTRY, ensure_ascii=False, indent=2))

def _load_registry():
    _ensure()
    try: return json.loads(REGISTRY.read_text())
    except Exception: return dict(DEFAULT_REGISTRY)

def _load_config():
    _ensure()
    try: return json.loads(CONFIG.read_text())
    except Exception: return {"mcpServers": {}}

def _save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
