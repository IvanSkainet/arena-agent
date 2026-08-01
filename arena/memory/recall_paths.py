"""Memory recall CLI implementation."""
from __future__ import annotations

import argparse  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import json  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import os
import re  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import sqlite3  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import sys  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
from collections import Counter  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
from pathlib import Path


def get_root_dir() -> Path:
    return Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()

def get_mem_dir() -> Path:
    return get_root_dir() / "memory"

def get_rpt_dir() -> Path:
    return get_root_dir() / "reports"

def get_sub_dir() -> Path:
    return get_root_dir() / "subagents"
