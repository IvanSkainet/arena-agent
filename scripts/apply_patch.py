#!/usr/bin/env python3
"""apply_patch.py - declarative patcher.

Usage:
  apply_patch.py <spec.json>

Spec format (JSON):
  {
    "title": "label",
    "steps": [ {step}, ... ]
  }

Step ops:
  ensure_dir   {"path": str, "mode": "0o700"}
  write_b64    {"path": str, "content_b64": str, "mode": "0o600"}
  patch_block  {"path": str, "anchor": str, "block": str,
                "marker": str, "position": "before|after|replace"}
  patch_replace {"path": str, "old": str, "new": str, "marker": str}
  verify_bash  {"path": str}
  verify_py    {"path": str}
  run          {"cmd": str, "timeout": 60}
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import datetime as dt
from pathlib import Path


def now_stamp():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_mode(m):
    if isinstance(m, int):
        return m
    if isinstance(m, str):
        if m.startswith("0o") or m.startswith("0O"):
            return int(m, 8)
        return int(m, 8) if m.startswith("0") else int(m)
    return 0o600


def backup(path: Path):
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak-" + now_stamp())
        shutil.copy2(path, bak)
        try:
            bak.chmod(0o600)
        except OSError:
            pass
        return bak
    return None


def safe_write(path: Path, data: bytes, mode: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    try:
        tmp.chmod(mode)
    except OSError:
        pass
    tmp.replace(path)
    try:
        path.chmod(mode)
    except OSError:
        pass


def step_ensure_dir(s):
    p = Path(os.path.expanduser(s["path"]))
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(parse_mode(s.get("mode", "0o700")))
    except OSError:
        pass
    return f"ensure_dir {p}"


def step_write_b64(s):
    p = Path(os.path.expanduser(s["path"]))
    if p.exists():
        backup(p)
    data = base64.b64decode(s["content_b64"])
    safe_write(p, data, parse_mode(s.get("mode", "0o600")))
    return f"write_b64 {p} ({len(data)} bytes)"


def step_patch_block(s):
    p = Path(os.path.expanduser(s["path"]))
    src = p.read_text(encoding="utf-8")
    marker = s["marker"]
    if marker in src:
        return f"patch_block {p}: already patched"
    anchor = s["anchor"]
    if anchor not in src:
        raise ValueError(f"anchor not found in {p}")
    block = s["block"]
    pos = s.get("position", "before")
    if pos == "before":
        new = src.replace(anchor, block + anchor, 1)
    elif pos == "after":
        new = src.replace(anchor, anchor + block, 1)
    elif pos == "replace":
        new = src.replace(anchor, block, 1)
    else:
        raise ValueError(f"bad position: {pos}")
    backup(p)
    safe_write(p, new.encode("utf-8"), p.stat().st_mode & 0o777)
    return f"patch_block {p} ({pos})"


def step_patch_replace(s):
    p = Path(os.path.expanduser(s["path"]))
    src = p.read_text(encoding="utf-8")
    marker = s.get("marker")
    if marker and marker in src:
        return f"patch_replace {p}: already patched"
    old = s["old"]
    if old not in src:
        raise ValueError(f"old text not found in {p}")
    backup(p)
    safe_write(p, src.replace(old, s["new"], 1).encode("utf-8"),
               p.stat().st_mode & 0o777)
    return f"patch_replace {p}"


def step_verify_bash(s):
    p = Path(os.path.expanduser(s["path"]))
    cp = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
    if cp.returncode != 0:
        raise RuntimeError(f"bash -n FAILED for {p}: {cp.stderr.strip()}")
    return f"verify_bash {p}: ok"


def step_verify_py(s):
    p = Path(os.path.expanduser(s["path"]))
    spec = importlib.util.spec_from_file_location("_chk", str(p))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no spec/loader for {p}")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return f"verify_py {p}: ok"


def step_run(s):
    cmd = s["cmd"]
    timeout = int(s.get("timeout", 60))
    cp = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                        timeout=timeout)
    out = (cp.stdout or "").rstrip()
    if cp.returncode != 0:
        raise RuntimeError(f"run failed ({cp.returncode}): {cmd}\n"
                           f"stdout: {out}\nstderr: {cp.stderr.strip()}")
    return f"run ok: {cmd[:60]}{'...' if len(cmd) > 60 else ''}\n{out}"


OPS = {
    "ensure_dir": step_ensure_dir,
    "write_b64": step_write_b64,
    "patch_block": step_patch_block,
    "patch_replace": step_patch_replace,
    "verify_bash": step_verify_bash,
    "verify_py": step_verify_py,
    "run": step_run,
}


def main():
    if len(sys.argv) != 2:
        print("usage: apply_patch.py <spec.json>", file=sys.stderr)
        return 2
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(f"=== {spec.get('title', 'patch')} ===")
    for i, step in enumerate(spec.get("steps", []), 1):
        op = step.get("op")
        fn = OPS.get(op)
        if not fn:
            print(f"[{i}] UNKNOWN OP: {op}", file=sys.stderr)
            return 1
        try:
            msg = fn(step)
            print(f"[{i}] {msg}")
        except Exception as e:
            print(f"[{i}] FAIL: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
