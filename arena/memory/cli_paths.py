"""Standalone memory CLI helpers."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

def get_mem_dir() -> Path:
    root = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
    return root / "memory"

def get_db_path() -> Path:
    return get_mem_dir() / "facts.db"

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
