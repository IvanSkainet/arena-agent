"""Agent-side helper utilities."""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
FACTS = ROOT / "memory" / "facts.jsonl"

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def safe_write(path: Path | str, content: str, mode: int = 0o600) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    try:
        tmp.chmod(mode)
    except OSError:
        pass
    tmp.replace(p)
    try:
        p.chmod(mode)  # ACL-proof: explicit chmod after replace
    except OSError:
        pass
    return p

def backup_file(path: Path | str) -> Path | None:
    p = Path(path)
    if not p.exists():
        return None
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = p.with_suffix(p.suffix + f".bak-{stamp}")
    shutil.copy2(p, bak)
    try:
        bak.chmod(0o600)
    except OSError:
        pass
    return bak

def verify_python(path: Path | str) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, f"missing: {p}"
    try:
        spec = importlib.util.spec_from_file_location("_check", str(p))
        if spec is None or spec.loader is None:
            return False, "no spec/loader"
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

def verify_bash(path: Path | str) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, f"missing: {p}"
    cp = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
    if cp.returncode == 0:
        return True, "ok"
    return False, (cp.stderr or cp.stdout or "non-zero exit").strip()

def patch_block(path: Path | str, anchor: str, new_block: str,
                marker: str, position: str = "before") -> str:
    """
    Insert `new_block` near `anchor` in file at `path`. Idempotent: if `marker`
    already present in file, no-op.

    position: 'before' (insert immediately before anchor)
              'after'  (insert immediately after anchor)
              'replace' (replace `anchor` with `new_block` — anchor must occur
                         exactly once)
    Returns status string.
    """
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    if marker and marker in src:
        return f"already patched (marker: {marker!r})"
    if anchor not in src:
        raise ValueError(f"anchor not found in {p}: {anchor!r}")
    if position == "before":
        new_src = src.replace(anchor, new_block + anchor, 1)
    elif position == "after":
        new_src = src.replace(anchor, anchor + new_block, 1)
    elif position == "replace":
        new_src = src.replace(anchor, new_block, 1)
    else:
        raise ValueError(f"unknown position: {position}")
    backup_file(p)
    safe_write(p, new_src, mode=p.stat().st_mode & 0o777)
    return "patched"

def patch_replace(path: Path | str, old: str, new: str,
                  marker: str | None = None) -> str:
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    if marker and marker in src:
        return f"already patched (marker: {marker!r})"
    if old not in src:
        raise ValueError(f"old text not found in {p}")
    backup_file(p)
    safe_write(p, src.replace(old, new, 1), mode=p.stat().st_mode & 0o777)
    return "patched"
