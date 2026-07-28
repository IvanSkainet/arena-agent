"""Persistent artifact store for Code Workbench runs."""
from __future__ import annotations

import base64
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any


def home() -> Path:
    return Path(os.environ.get("ARENA_AGENT_HOME") or (Path.home() / "arena-bridge")).expanduser()


def runs_root() -> Path:
    p = home() / "code-runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_run_id(run_id: str) -> str:
    rid = str(run_id or "").strip()
    if not rid or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in rid):
        raise ValueError("invalid run_id")
    return rid


def safe_rel(path: str) -> Path:
    rel = Path(str(path).replace("\\", "/"))
    if not str(path).strip() or rel.is_absolute() or rel.drive or any(part in ("..", "") for part in rel.parts):
        raise ValueError("invalid artifact path")
    return rel


def persist_run(run_id: str, scratch: Path, artifact_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rid = safe_run_id(run_id)
    base = runs_root() / rid
    art_root = base / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    persisted = []
    for item in artifact_items:
        rel = safe_rel(str(item.get("path") or ""))
        src = scratch / rel
        if not src.is_file():
            continue
        dst = art_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        enriched = dict(item)
        enriched["download_url"] = f"/v1/code/runs/{rid}/artifacts/{rel.as_posix()}"
        persisted.append(enriched)
    meta = {"ok": True, "run_id": rid, "created_at": int(time.time()), "artifacts": persisted}
    (base / "run.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return persisted


def run_info(run_id: str) -> dict[str, Any]:
    p = runs_root() / safe_run_id(run_id) / "run.json"
    if not p.exists():
        return {"ok": False, "error": "run not found"}
    return json.loads(p.read_text(encoding="utf-8"))


def read_artifact(run_id: str, path: str, *, max_bytes: int = 128 * 1024) -> dict[str, Any]:
    rid = safe_run_id(run_id)
    rel = safe_rel(path)
    fp = runs_root() / rid / "artifacts" / rel
    if not fp.is_file():
        return {"ok": False, "error": "artifact not found"}
    data = fp.read_bytes()
    sample = data[:max_bytes]
    out: dict[str, Any] = {"ok": True, "run_id": rid, "path": rel.as_posix(), "bytes": len(data), "truncated": len(data) > max_bytes}
    try:
        out["text"] = sample.decode("utf-8")
    except UnicodeDecodeError:
        out["base64"] = base64.b64encode(sample).decode("ascii")
    return out
