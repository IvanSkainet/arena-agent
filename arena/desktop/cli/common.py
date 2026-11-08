"""Desktop manager CLI implementation."""
from __future__ import annotations

import argparse  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import datetime as dt
import json
import os  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import random  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import re  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import shutil
import subprocess
import sys  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import time  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
from pathlib import Path  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)

from arena.home import agent_home

ROOT = agent_home()
REPORTS = ROOT / "reports"
_wm_started = False

def stamp(): return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')

def run(cmd, timeout=20): return subprocess.run(cmd,shell=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)  # nosec B602 -- CLI helper used only by arena/desktop/cli/*; callers pass hard-coded fragments (see grep in the same dir).  # nosemgrep: subprocess-shell-true -- legitimate CLI-side helper (see bandit B602 nosec on the same line for the specific rationale)

def have(c): return shutil.which(c) is not None

def j(o): print(json.dumps(o,ensure_ascii=False,indent=2))
