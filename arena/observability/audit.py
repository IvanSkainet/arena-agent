"""Audit log helpers: redaction, append/rotation, tail and stats."""
from __future__ import annotations

import collections
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

from arena.constants import AUDIT_CMD_LIMIT

audit_lock = threading.Lock()


def sanitize_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in event.items():
        low_key = key.lower()
        if "token" in low_key or "authorization" in low_key or "password" in low_key or "secret" in low_key:
            out[key] = "<redacted>"
            continue
        if key == "cmd" and isinstance(value, str):
            out["cmd_len"] = len(value)
            out["cmd_sha256"] = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()
            if len(value) > AUDIT_CMD_LIMIT:
                out[key] = value[:AUDIT_CMD_LIMIT] + f"\n...[truncated {len(value) - AUDIT_CMD_LIMIT} chars; sha256={out['cmd_sha256']}]"
                out["cmd_truncated"] = True
            else:
                out[key] = value
                out["cmd_truncated"] = False
            continue
        if isinstance(value, str) and len(value) > 12000:
            out[key] = value[:12000] + f"\n...[truncated {len(value) - 12000} chars]"
            out[key + "_truncated"] = True
        else:
            out[key] = value
    return out


def write_audit_event(
    event: dict[str, Any],
    *,
    audit_path: Path,
    app_dir: Path,
    utc_now_fn: Callable[[], str],
    lock: threading.Lock = audit_lock,
) -> dict[str, Any]:
    """Sanitize, timestamp, append and rotate an audit event; return written event."""
    app_dir.mkdir(parents=True, exist_ok=True)
    written = {"ts": utc_now_fn(), **sanitize_audit_event(event)}
    line = json.dumps(written, ensure_ascii=False, sort_keys=True) + "\n"
    with lock:
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(line)
        try:
            os.chmod(audit_path, 0o600)
        except Exception:
            pass
        try:
            if audit_path.exists() and audit_path.stat().st_size > 50 * 1024 * 1024:
                for i in range(5, 0, -1):
                    old = app_dir / f"audit.jsonl.{i}"
                    if old.exists():
                        if i == 5:
                            old.unlink()
                        else:
                            old.rename(app_dir / f"audit.jsonl.{i + 1}")
                audit_path.rename(app_dir / "audit.jsonl.1")
        except Exception:
            pass
    return written


def read_tail(path: Path, lines: int = 100) -> list[str]:
    """Read last N lines efficiently using deque."""
    if not path.exists():
        return []
    lines = max(1, min(lines, 1000))
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return list(collections.deque(f, maxlen=lines))
    except Exception:
        return []


def audit_stats(audit_path: Path) -> dict[str, Any]:
    if not audit_path.exists():
        return {"ok": True, "total": 0, "by_type": {}, "first_ts": None, "last_ts": None}
    by_type: dict[str, int] = collections.Counter()
    total = 0
    first_ts: str | None = None
    last_ts: str | None = None
    with open(audit_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                total += 1
                event_type = event.get("type", "unknown")
                by_type[event_type] += 1
                ts = event.get("ts", "")
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
            except json.JSONDecodeError:
                total += 1
                by_type["parse_error"] += 1
    return {"ok": True, "total": total, "by_type": dict(by_type), "first_ts": first_ts, "last_ts": last_ts}
