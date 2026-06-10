"""Small hot-reload cache for skill registry scans."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable


class SkillsCache:
    def __init__(self, *, skills_dir: Path, scan_fn: Callable[[], dict[str, Any]], ttl: float = 5.0, hot_reload: bool = True):
        self.skills_dir = skills_dir
        self.scan_fn = scan_fn
        self.ttl = ttl
        self.hot_reload = hot_reload
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"last_scan": 0.0, "skills": [], "mtimes": {}}

    def reset(self) -> None:
        with self._lock:
            self._state = {"last_scan": 0.0, "skills": [], "mtimes": {}}

    def _current_mtimes(self) -> dict[str, float]:
        current: dict[str, float] = {}
        if not self.skills_dir.exists():
            return current
        for path in sorted(self.skills_dir.rglob("*")):
            if path.is_file() and path.suffix in (".json", ".yaml", ".yml", ".md", ".toml", ".sh", ".py"):
                try:
                    current[str(path)] = path.stat().st_mtime
                except OSError:
                    pass
        return current

    def list(self) -> dict[str, Any]:
        """Return cached skill list, rescanning when stale or mtimes changed."""
        with self._lock:
            now = time.time()
            if not self.hot_reload and (now - self._state["last_scan"]) < self.ttl:
                return {"ok": True, "count": len(self._state["skills"]), "skills": self._state["skills"], "cached": True}

            changed = False
            if self._state["last_scan"] > 0 and self.skills_dir.exists():
                current_mtimes = self._current_mtimes()
                if current_mtimes != self._state["mtimes"]:
                    changed = True
                    self._state["mtimes"] = current_mtimes
            else:
                changed = True

            if not changed and (now - self._state["last_scan"]) < self.ttl:
                return {"ok": True, "count": len(self._state["skills"]), "skills": self._state["skills"], "cached": True}

        result = self.scan_fn()

        with self._lock:
            self._state["skills"] = result.get("skills", [])
            self._state["last_scan"] = time.time()
            result["cached"] = False
            result["hot_reload"] = self.hot_reload
        return result
