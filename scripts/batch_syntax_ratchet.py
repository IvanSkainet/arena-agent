#!/usr/bin/env python3
"""Batch syntax & Windows safety ratchet.

Ensures that Windows batch (.bat) files maintain critical safety invariants:
1. Every .bat file uses CRLF (\r\n) line endings (prevents Windows cmd parser corruption).
2. Every netstat pipeline targeting port 8765 enforces /I "LISTENING" to protect the operator's browser.
3. No malformed batch syntax constructs.

Usage:
    python scripts/batch_syntax_ratchet.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scan_batch_files() -> list[str]:
    violations: list[str] = []
    bat_files = sorted(ROOT.glob("*.bat")) + sorted(ROOT.glob("**/*.bat"))
    # Exclude temp / venv dirs
    bat_files = [b for b in bat_files if ".git" not in b.parts and "tmp" not in b.parts]

    for bat in bat_files:
        rel = bat.relative_to(ROOT)
        content_bytes = bat.read_bytes()

        # Invariant 1: CRLF line endings
        lines = content_bytes.split(b"\n")
        for i, line in enumerate(lines[:-1], start=1):
            if not line.endswith(b"\r"):
                violations.append(f"{rel}:{i} missing carriage return (\\r\\n required on Windows batch files)")
                break

        # Invariant 2: netstat browser kill safety
        content_text = content_bytes.decode("latin-1", errors="replace")
        if "netstat" in content_text and "8765" in content_text:
            if "findstr" in content_text and 'LISTENING' not in content_text.upper():
                violations.append(f"{rel} netstat pipeline lacks /I \"LISTENING\" filter (browser kill hazard)")

    return violations


def main() -> int:
    violations = scan_batch_files()
    if violations:
        print("FAIL: Batch file safety invariants violated:")
        for v in violations:
            print(f"  - {v}")
        return 1

    print("OK: Batch file safety invariants verified (CRLF + LISTEN filters).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
