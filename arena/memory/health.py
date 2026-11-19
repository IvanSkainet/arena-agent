"""Persistent, path-redacted health after a corruption recovery."""
from __future__ import annotations

from pathlib import Path

from arena.private_state import write_private_json


def recovery_record(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".recovered.json")


def record_recovery(db_path: Path, quarantine: Path) -> None:
    # Kept across restarts: a fresh empty DB is usable, not proof old facts
    # were restored. The operator acknowledges recovery by removing this
    # record only after inspecting/restoring the private quarantined bytes.
    write_private_json(recovery_record(db_path), {"status": "rebuilt", "quarantine": str(quarantine)})


def memory_status(db_path: Path) -> str:
    if (recovery_record(db_path).exists()
            or db_path.with_name(db_path.name + ".recovery-incomplete").exists()):
        return "rebuilt"
    return "ok" if db_path.exists() else "empty"
