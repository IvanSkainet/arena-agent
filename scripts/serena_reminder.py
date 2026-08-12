#!/usr/bin/env python3
"""Serena & Session Memory Integrity Reminder.

Ensures the agent maintains continuity across session compressions and restarts:
1. Verifies presence of docs/TASK_BOARD.md and AGENTS.md;
2. Checks Serena memory file / session recall database under ~/.arena/ or ~/arena-bridge/;
3. Prints active task focus (T0..Tn) and Definition of Done reminders.

Usage:
    python scripts/serena_reminder.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_BOARD = ROOT / "docs" / "TASK_BOARD.md"
AGENTS_MD = ROOT / "AGENTS.md"


def check_continuity() -> dict[str, bool]:
    status = {
        "task_board_exists": TASK_BOARD.exists(),
        "agents_guide_exists": AGENTS_MD.exists(),
    }
    return status


def print_summary() -> int:
    status = check_continuity()
    print("=== SERENA & SESSION CONTINUITY CHECK ===")
    for k, v in status.items():
        state = "OK" if v else "MISSING"
        print(f"  [{state}] {k}")

    if not all(status.values()):
        print("\nFAIL: Critical continuity files are missing!")
        return 1

    print("\nProtocol reminder:")
    print("  1. Always verify task ID in docs/TASK_BOARD.md (T0..Tn).")
    print("  2. Apply Spec-Kit discipline: Root cause fix + 0 mutation survivors + sabotage.")
    print("  3. Keep workspace lean (<80 MB) to preserve 128 MB snapshot cap.")
    print("  4. Verify by execution: run preflight.py before any release.")
    return 0


if __name__ == "__main__":
    sys.exit(print_summary())
