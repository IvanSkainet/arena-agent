"""Bridge configuration and port bootstrap helpers."""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path


def load_config_file(
    *,
    log_info: Callable[..., None] | None = None,
    log_debug: Callable[..., None] | None = None,
    log_warning: Callable[..., None] | None = None,
) -> dict:
    """Load optional bridge.yml or bridge.json configuration file."""
    search_paths: list[Path] = []
    env_home = os.environ.get("ARENA_AGENT_HOME")
    if env_home:
        search_paths.append(Path(env_home) / "bridge.yml")
    search_paths.append(Path.home() / "arena-bridge" / "bridge.yml")
    search_paths.append(Path("bridge.yml"))

    for path in search_paths:
        if path.exists():
            try:
                import yaml
                with open(path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                if log_info:
                    log_info("[Config] Loaded configuration from %s", path)
                return cfg
            except ImportError:
                json_path = path.with_suffix(".json")
                if json_path.exists():
                    try:
                        with open(json_path, encoding="utf-8") as f:
                            cfg = json.load(f) or {}
                        if log_info:
                            log_info("[Config] Loaded JSON configuration from %s", json_path)
                        return cfg
                    except Exception:
                        pass
                if log_debug:
                    log_debug("[Config] bridge.yml found at %s but PyYAML not installed, skipping", path)
                return {}
            except Exception as e:
                if log_warning:
                    log_warning("[Config] Failed to load %s: %s", path, e)
                return {}
    return {}


def get_bridge_port() -> int:
    """Get the port the bridge is running on (from environment or default 8765)."""
    try:
        return int(os.environ.get("ARENA_PORT", "8765"))
    except (ValueError, TypeError):
        return 8765
