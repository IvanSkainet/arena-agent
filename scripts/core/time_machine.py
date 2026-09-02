#!/usr/bin/env python3
"""
Snapshot & Rollback System (Time Machine)
Creates lightweight backups of the current directory.
"""
import datetime
import glob
import os
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from arena.files.safe_extract import (  # noqa: E402
    UnsafeArchiveError,
    safe_extract_tar,
)

CACHE_DIR = os.path.expanduser("~/.arena-snapshots")

def make_snapshot(cwd: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bname = os.path.basename(os.path.abspath(cwd))
    if not bname:
        bname = "root"

    arc_name = os.path.join(CACHE_DIR, f"{bname}_{ts}.tar.gz")

    print(f"Creating snapshot of {cwd}...")
    try:
        with tarfile.open(arc_name, "w:gz") as tar:
            for item in os.listdir(cwd):
                # Skip heavy/unnecessary folders
                if item in ['.git', 'node_modules', '.venv', '__pycache__']:
                    continue
                tar.add(os.path.join(cwd, item), arcname=item)
        print(f"Snapshot saved: {arc_name}")
        return True
    except Exception as e:
        print(f"Failed to create snapshot: {e}")
        return False

def list_snapshots(cwd: str):
    bname = os.path.basename(os.path.abspath(cwd))
    if not bname:
        bname = "root"
    files = glob.glob(os.path.join(CACHE_DIR, f"{bname}_*.tar.gz"))
    if not files:
        print(f"No snapshots found for '{bname}' in {CACHE_DIR}")
        return

    files.sort(reverse=True)
    print("Available snapshots:")
    for i, f in enumerate(files):
        sz = os.path.getsize(f) / (1024*1024)
        print(f"[{i}] {os.path.basename(f)} ({sz:.2f} MB)")

def rollback(cwd: str, index: int = 0):
    bname = os.path.basename(os.path.abspath(cwd))
    if not bname:
        bname = "root"
    files = glob.glob(os.path.join(CACHE_DIR, f"{bname}_*.tar.gz"))
    files.sort(reverse=True)

    if index >= len(files):
        print(f"Invalid snapshot index. Max index is {len(files)-1}")
        return

    arc_name = files[index]
    print(f"Rolling back to {arc_name}...")

    try:
        # Extracts over existing files, so a hostile archive here would
        # be writing into a live working tree. safe_extract_tar refuses
        # members that escape `cwd`, link members, and device nodes.
        #
        # A bare tar.extractall() used to sit here. It is not merely
        # theoretical: a snapshot containing `../../escaped.txt` wrote
        # outside the target directory on this repo (#242). Snapshots
        # are usually self-produced, but ~/.arena-snapshots is an
        # ordinary user-writable directory and rollback picks whatever
        # file sorts first.
        safe_extract_tar(arc_name, cwd)
        print("Rollback complete.")
    except UnsafeArchiveError as e:
        print(f"Rollback refused: {e}")
        return False
    except Exception as e:
        print(f"Rollback failed: {e}")
        return False
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: time_machine.py [snapshot|list|rollback <idx>]")
        sys.exit(1)

    cmd = sys.argv[1]
    cwd = os.getcwd()

    if cmd == "snapshot":
        make_snapshot(cwd)
    elif cmd == "list":
        list_snapshots(cwd)
    elif cmd == "rollback":
        idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        rollback(cwd, idx)
