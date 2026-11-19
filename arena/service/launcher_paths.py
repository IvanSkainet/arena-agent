"""Find legacy install launchers or the current state-root repair launchers."""
from __future__ import annotations

from pathlib import Path

from arena.home import agent_home


def windows_launcher_root(install_root: Path | str) -> Path:
    install = Path(install_root)
    if all((install / name).is_file() for name in ("start_hidden.vbs", "start_bridge.bat")):
        return install
    state = agent_home()
    if all((state / name).is_file() for name in ("start_hidden.vbs", "start_bridge.bat")):
        return state
    return install


def _has_mkdtemp_suffix(part: str, prefix: str) -> bool:
    """
    True if `part` is `prefix` followed by a `mkdtemp` suffix.

    `mkdtemp` appends exactly eight characters from `[a-z0-9_]`. A
    deliberate name such as `mcp-dispatch-production` does not have
    that shape, which is the distinction that keeps a real install
    directory out of the refusal (review).
    """
    if not part.startswith(prefix):
        return False
    suffix = part[len(prefix):]
    return len(suffix) == 8 and all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in suffix)
