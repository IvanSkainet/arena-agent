"""agentctl extras CLI implementation."""
from __future__ import annotations

import json  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import os  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import platform  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import shutil
import socket  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import subprocess  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import sys
import time  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
from pathlib import Path

from arena.home import agent_home, executable_root

ROOT = agent_home()
AGENTCTL = executable_root() / "bin" / "agentctl"
_VENV_CANDIDATES = [executable_root() / ".venv" / "bin" / "python", executable_root() / ".venv" / "Scripts" / "python.exe"]
PY = next((c for c in _VENV_CANDIDATES if c.exists()), None)
if PY is None:
    for cmd in [sys.executable, "python3", "python"]:
        p = shutil.which(cmd)
        if p:
            PY = Path(p)
            break
    else:
        PY = Path("python3")

