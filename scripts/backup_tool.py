#!/usr/bin/env python3
from __future__ import annotations
import datetime as dt
import os
import zipfile
from pathlib import Path

ROOT = Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home() / 'arena-bridge'))).expanduser()
B = ROOT / 'backups'

# Exclude list to avoid bloating or leaking private details
EXCLUDES = ['backups', 'logs', 'node_modules', '__pycache__', '.venv', '.git', 'token.txt']

def main():
    B.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_zip = B / f'arena-bridge-backup-{timestamp}.zip'
    
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 1. Archive the entire arena-bridge folder
        for root, dirs, files in os.walk(ROOT):
            # Exclude directories on-the-fly
            dirs[:] = [d for d in dirs if d not in EXCLUDES]
            for file in files:
                if file in EXCLUDES or file.endswith('.zip') or file.endswith('.tgz'):
                    continue
                file_path = os.path.join(root, file)
                rel_path = os.path.join('arena-bridge', os.path.relpath(file_path, ROOT))
                zipf.write(file_path, rel_path)
                
        # 2. Archive the arena-local-bridge folder if it exists
        bridge_root = ROOT.parent / 'arena-local-bridge'
        if bridge_root.exists():
            for root, dirs, files in os.walk(bridge_root):
                dirs[:] = [d for d in dirs if d not in EXCLUDES]
                for file in files:
                    if file in EXCLUDES:
                        continue
                    file_path = os.path.join(root, file)
                    rel_path = os.path.join('arena-local-bridge', os.path.relpath(file_path, bridge_root))
                    zipf.write(file_path, rel_path)
                    
    print(out_zip)

if __name__ == '__main__':
    main()
