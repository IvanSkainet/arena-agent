"""Desktop manager CLI implementation."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
REPORTS = ROOT / "reports"
_wm_started = False

def stamp(): return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')

def run(cmd, timeout=20): return subprocess.run(cmd,shell=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)  # nosec B602 -- CLI helper used only by arena/desktop/cli/*; callers pass hard-coded fragments (see grep in the same dir).  # nosemgrep: subprocess-shell-true -- legitimate CLI-side helper (see bandit B602 nosec on the same line for the specific rationale)

def have(c): return shutil.which(c) is not None

def j(o): print(json.dumps(o,ensure_ascii=False,indent=2))
