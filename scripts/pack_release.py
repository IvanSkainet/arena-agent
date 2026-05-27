import os
import zipfile
from pathlib import Path

HOME = Path.home()
AGENT_DIR = HOME / "arena-bridge"
BRIDGE_DIR = HOME / "arena-local-bridge"
OUT_ZIP = HOME / "arena_agent_release.zip"

EXCLUDE_PATTERNS = [
    '.git',
    '__pycache__',
    '.venv',
    'node_modules',
    'backups/',
    'logs/',
    'reports/',
    'queue/inbox/',
    'queue/running/',
    'queue/done/',
    'queue/failed/',
    'subagents/',
    'memory/',
    'missions/',
    'projects/',
    'tools/superpowers/',
    'arena_agent_release.zip',
    '.pyc',
    '.bak-',
    'recover',
    '.bak',
    'tabs_state.json',
    'dashboard_v2.html',
    'dashboard_v3.html',
    'WINDOWS_INSTALL.md',
    'README_FRIEND_RU.md',
    'README_WINDOWS_RU.md',
    'recover_bridge_and_tabs.sh',
    'recover_bridge_and_tabs_v2.sh',
    'recover.sh',
    'recover (1).sh',
]

def should_exclude(path: Path, base: Path) -> bool:
    rel = str(path.relative_to(base))
    if path.is_dir():
        rel += '/'
    for pat in EXCLUDE_PATTERNS:
        if pat.endswith('/'):
            if rel.startswith(pat) or f'/{pat}' in rel:
                return True
        else:
            if pat in rel:
                return True
    return False

def pack():
    print("=== ARENA AGENT RELEASE PACKAGING ===")
    if not AGENT_DIR.exists():
        print(f"ERROR: {AGENT_DIR} not found")
        return

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
        print("Removed old release ZIP")

    with zipfile.ZipFile(OUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(AGENT_DIR):
            dirs[:] = [d for d in dirs if not should_exclude(Path(root) / d, AGENT_DIR)]
            for file in files:
                fp = Path(root) / file
                if should_exclude(fp, AGENT_DIR):
                    continue
                rel_zip = Path('arena-bridge') / fp.relative_to(AGENT_DIR)
                z.write(fp, rel_zip)
                print(f"  + {rel_zip}")

        lb = BRIDGE_DIR / 'local_bridge.py'
        if lb.exists():
            rel_lb = Path('arena-local-bridge') / 'local_bridge.py'
            z.write(lb, rel_lb)
            print(f"  + {rel_lb}")
        else:
            print(f"  WARNING: {lb} not found (skipped)")

        placeholders = [
            'arena-bridge/backups/.gitkeep',
            'arena-bridge/logs/.gitkeep',
            'arena-bridge/reports/shots/.gitkeep',
            'arena-bridge/reports/snapshots/.gitkeep',
            'arena-bridge/reports/recordings/.gitkeep',
            'arena-bridge/queue/inbox/.gitkeep',
            'arena-bridge/queue/running/.gitkeep',
            'arena-bridge/queue/done/.gitkeep',
            'arena-bridge/queue/failed/.gitkeep',
            'arena-bridge/subagents/.gitkeep',
            'arena-bridge/memory/sessions/.gitkeep',
            'arena-bridge/missions/.gitkeep',
            'arena-bridge/projects/.gitkeep',
        ]
        for p in placeholders:
            z.writestr(p, '')
            print(f"  + {p} (placeholder)")

    size_mb = OUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"\n=== DONE ===")
    print(f"Release ZIP: {OUT_ZIP}")
    print(f"Size: {size_mb:.2f} MB")

if __name__ == "__main__":
    pack()
