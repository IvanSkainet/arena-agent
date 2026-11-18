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

from arena.home import agent_home, code_root

ROOT = agent_home()
AGENTCTL = code_root() / "bin" / "agentctl"
_VENV_CANDIDATES = [code_root() / ".venv" / "bin" / "python", code_root() / ".venv" / "Scripts" / "python.exe"]
PY = next((c for c in _VENV_CANDIDATES if c.exists()), None)
if PY is None:
    for cmd in [sys.executable, "python3", "python"]:
        p = shutil.which(cmd)
        if p:
            PY = Path(p)
            break
    else:
        PY = Path("python3")

