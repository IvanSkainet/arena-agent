# ruff: noqa: F821
"""Legacy path constants wiring for unified_bridge."""
from __future__ import annotations

from typing import Any, MutableMapping


def build_legacy_paths(g: MutableMapping[str, Any]) -> dict[str, Any]:
    paths = g["ArenaPaths"].from_env(g["BRIDGE_DIR"])
    return {
        "PATHS": paths,
        "ROOT_AGENT": paths.root_agent,
        "QUEUE": paths.queue,
        "INBOX": paths.inbox,
        "RUNNING": paths.running,
        "DONE": paths.done,
        "FAILED": paths.failed,
        "SKILLS_DIR": paths.skills_dir,
        "HOOKS_DIR": paths.hooks_dir,
        "AGENTS_DIR": paths.agents_dir,
        "SUBAGENTS_DIR": paths.subagents_dir,
        "MEMORY_FILE": paths.memory_file,
        "MEMORY_DB": paths.memory_db,
        "MISSIONS_DIR": paths.missions_dir,
        "REPORTS_DIR": paths.reports_dir,
        "WEBHOOKS_FILE": paths.webhooks_file,
    }


__all__ = ["build_legacy_paths"]
