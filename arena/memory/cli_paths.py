"""Standalone memory CLI helpers."""
from __future__ import annotations

import argparse  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import datetime as dt
import json  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import sqlite3  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import sys  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
from pathlib import Path

from arena.home import agent_home


def get_mem_dir() -> Path:
    root = agent_home()
    return root / "memory"

def get_db_path() -> Path:
    return get_mem_dir() / "facts.db"

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
