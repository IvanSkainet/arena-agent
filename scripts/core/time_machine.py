#!/usr/bin/env python3
"""
Snapshot & Rollback System (Time Machine)
Creates lightweight backups of the current directory.
"""
import sys, os, tarfile, datetime, glob

CACHE_DIR = os.path.expanduser("~/.arena-snapshots")

def make_snapshot(cwd: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bname = os.path.basename(os.path.abspath(cwd))
    if not bname: bname = "root"
    
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
    if not bname: bname = "root"
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
    if not bname: bname = "root"
    files = glob.glob(os.path.join(CACHE_DIR, f"{bname}_*.tar.gz"))
    files.sort(reverse=True)
    
    if index >= len(files):
        print(f"Invalid snapshot index. Max index is {len(files)-1}")
        return
        
    arc_name = files[index]
    print(f"Rolling back to {arc_name}...")
    
    try:
        # Dangerous operation: usually requires care. We'll extract over existing files.
        with tarfile.open(arc_name, "r:gz") as tar:
            tar.extractall(path=cwd)
        print("Rollback complete.")
    except Exception as e:
        print(f"Rollback failed: {e}")

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
