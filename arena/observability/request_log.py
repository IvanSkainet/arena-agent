"""Request/response JSONL log helpers."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

request_log_lock = threading.Lock()
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3


def log_request_response(
    *,
    log_file: Path,
    app_dir: Path,
    utc_now_fn: Callable[[], str],
    method: str,
    path: str,
    status: int,
    duration: float,
    req_id: str,
    peer: str = "",
    error: str = "",
    lock: threading.Lock = request_log_lock,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> None:
    """Append one request/response entry and rotate if necessary."""
    entry: dict[str, Any] = {
        "ts": utc_now_fn(),
        "req_id": req_id,
        "method": method,
        "path": path,
        "status": status,
        "duration_ms": round(duration * 1000, 2),
        "peer": peer,
    }
    if error:
        entry["error"] = error[:500]
    try:
        app_dir.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > max_bytes:
            for i in range(backup_count, 0, -1):
                old = app_dir / f"requests.jsonl.{i}"
                older = app_dir / f"requests.jsonl.{i + 1}"
                if old.exists():
                    if i == backup_count:
                        old.unlink()
                    else:
                        try:
                            old.rename(older)
                        except OSError:
                            pass
            try:
                log_file.rename(app_dir / "requests.jsonl.1")
            except OSError:
                pass
        with lock:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_request_log(
    log_file: Path,
    *,
    lines_count: int = 100,
    method_filter: str = "",
    path_filter: str = "",
    status_filter: str = "",
) -> list[dict[str, Any]]:
    """Read filtered request log entries, most recent first."""
    entries: list[dict[str, Any]] = []
    lines_count = min(max(1, lines_count), 1000)
    method_filter = (method_filter or "").upper()
    path_filter = path_filter or ""
    status_filter = status_filter or ""
    try:
        if not log_file.exists():
            return []
        all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(all_lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if method_filter and entry.get("method", "").upper() != method_filter:
                continue
            if path_filter and path_filter not in entry.get("path", ""):
                continue
            if status_filter:
                try:
                    if entry.get("status", 0) != int(status_filter):
                        continue
                except ValueError:
                    pass
            entries.append(entry)
            if len(entries) >= lines_count:
                break
    except Exception:
        return entries
    return entries


# Backward-compatible private alias.
_log_request_response = log_request_response
