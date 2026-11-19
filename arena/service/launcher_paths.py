"""Find legacy install launchers or the current state-root repair launchers."""
from __future__ import annotations

from pathlib import Path

from arena.home import agent_home


def windows_launcher_root(install_root: Path | str) -> Path:
    install = Path(install_root)
    if any((install / name).is_file() for name in ("start_hidden.vbs", "start_bridge.bat")):
        return install
    state = agent_home()
    if any((state / name).is_file() for name in ("start_hidden.vbs", "start_bridge.bat")):
        return state
    return install
