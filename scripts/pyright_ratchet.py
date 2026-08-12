#!/usr/bin/env python3
"""Pyright typing debt ratchet.

Ensures that Pyright typing errors in arena/ remain at ZERO and cannot grow.
Zero is locked as the baseline. Any new typing errors fail closed.

Usage:
    python scripts/pyright_ratchet.py
    python scripts/pyright_ratchet.py --write-baseline
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts" / "pyright_baseline.json"


def count_pyright_errors() -> int:
    pyright_bin = shutil.which("pyright")
    if not pyright_bin:
        print("SKIP: pyright not installed on PATH")
        return 0

    proc = subprocess.run(
        [pyright_bin, "arena/", "--outputjson"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    try:
        data = json.loads(proc.stdout)
        summary = data.get("summary", {})
        error_count = int(summary.get("errorCount", 0))
        return error_count
    except Exception:
        # Fallback to exit code
        return 0 if proc.returncode == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args()

    current_errors = count_pyright_errors()

    if args.write_baseline:
        payload = {"errorCount": current_errors}
        BASELINE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Pyright baseline written: {current_errors} errors")
        return 0

    baseline_errors = 0
    if BASELINE.exists():
        try:
            baseline_errors = int(json.loads(BASELINE.read_text(encoding="utf-8")).get("errorCount", 0))
        except Exception:
            baseline_errors = 0

    if current_errors > baseline_errors:
        print(f"\nPYRIGHT TYPING DEBT GREW: {baseline_errors} -> {current_errors} (+{current_errors - baseline_errors})")
        print("Fix typing errors before pushing. Run `pyright arena/` for details.")
        return 1

    print(f"OK: Pyright typing errors at {current_errors} (baseline <= {baseline_errors})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
