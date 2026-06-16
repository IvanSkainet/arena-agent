"""Memory recall CLI implementation."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

def get_root_dir() -> Path:
    return Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()

def get_mem_dir() -> Path:
    return get_root_dir() / "memory"

def get_rpt_dir() -> Path:
    return get_root_dir() / "reports"

def get_sub_dir() -> Path:
    return get_root_dir() / "subagents"
