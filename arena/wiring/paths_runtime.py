"""path constants wiring for unified_bridge."""
from __future__ import annotations

from typing import Any, MutableMapping


def build_paths_runtime(g: MutableMapping[str, Any]) -> dict[str, Any]:
    # No argument: the data directory is ARENA_AGENT_HOME / ~/arena-bridge.
    # Passing BRIDGE_DIR here is what used to fill the checkout (or
    # site-packages) with queue/missions/relay on a default run.
    paths = g["ArenaPaths"].from_env()
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


__all__ = ["build_paths_runtime"]
