"""agentctl extras CLI implementation."""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", os.path.expanduser("~/arena-bridge")))
AGENTCTL = ROOT / "bin" / "agentctl"
_VENV_CANDIDATES = [ROOT / ".venv" / "bin" / "python", ROOT / ".venv" / "Scripts" / "python.exe"]
PY = next((c for c in _VENV_CANDIDATES if c.exists()), None)
if PY is None:
    for cmd in [sys.executable, "python3", "python"]:
        p = shutil.which(cmd)
        if p:
            PY = Path(p)
            break
    else:
        PY = Path("python3")

