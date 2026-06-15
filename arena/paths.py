"""Filesystem path layout for the Arena bridge runtime."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArenaPaths:
    root_agent: Path
    queue: Path
    inbox: Path
    running: Path
    done: Path
    failed: Path
    skills_dir: Path
    hooks_dir: Path
    agents_dir: Path
    subagents_dir: Path
    memory_file: Path
    memory_db: Path
    missions_dir: Path
    reports_dir: Path
    webhooks_file: Path

    @classmethod
    def from_env(cls, bridge_dir: Path) -> "ArenaPaths":
        root_agent = Path(os.environ.get("ARENA_AGENT_HOME", str(bridge_dir))).expanduser()
        queue = root_agent / "queue"
        return cls(
            root_agent=root_agent,
            queue=queue,
            inbox=queue / "inbox",
            running=queue / "running",
            done=queue / "done",
            failed=queue / "failed",
            skills_dir=root_agent / "skills",
            hooks_dir=root_agent / "hooks",
            agents_dir=root_agent / "agents",
            subagents_dir=root_agent / "subagents",
            memory_file=root_agent / "memory" / "facts.jsonl",
            memory_db=root_agent / "memory" / "facts.db",
            missions_dir=root_agent / "missions",
            reports_dir=root_agent / "reports",
            webhooks_file=root_agent / "webhooks.json",
        )
