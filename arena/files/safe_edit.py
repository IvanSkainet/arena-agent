"""Preview/confirm/rollback helpers for safe text edits."""
from __future__ import annotations

import difflib
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_PREVIEW_TTL_S = 30 * 60
_ROLLBACK_TTL_S = 24 * 60 * 60
_MAX_PREVIEWS = 200
_MAX_ROLLBACKS = 200
_PREVIEWS: dict[str, dict[str, Any]] = {}
_ROLLBACKS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _cleanup_state(now: float) -> None:
    for store, ttl in ((_PREVIEWS, _PREVIEW_TTL_S), (_ROLLBACKS, _ROLLBACK_TTL_S)):
        stale = [key for key, meta in store.items() if now - float(meta.get("created_at_ts", now)) > ttl]
        for key in stale:
            store.pop(key, None)
        if len(store) > (_MAX_PREVIEWS if store is _PREVIEWS else _MAX_ROLLBACKS):
            items = sorted(store.items(), key=lambda item: float(item[1].get("created_at_ts", 0.0)))
            excess = len(store) - (_MAX_PREVIEWS if store is _PREVIEWS else _MAX_ROLLBACKS)
            for key, _meta in items[:excess]:
                store.pop(key, None)



def build_edit_preview(path: Path, old_text: str, new_text: str, *, replace_all: bool) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"ok": False, "error": "file not found", "status": 404}
    except PermissionError:
        return {"ok": False, "error": "permission denied", "status": 403}
    except UnicodeDecodeError:
        return {"ok": False, "error": "file is not valid utf-8 (binary file)", "status": 400}
    if not old_text:
        return {"ok": False, "error": "missing or empty 'old_text'", "status": 400}
    count = content.count(old_text)
    if count == 0:
        return {"ok": False, "error": f"old_text not found in {path}", "status": 404}
    if count > 1 and not replace_all:
        return {"ok": False, "error": f"old_text matches {count} times; make it unique or set replace_all=true", "status": 409}
    if old_text == new_text:
        return {
            "ok": True,
            "path": str(path),
            "replacements": 0,
            "bytes_before": len(content),
            "bytes_after": len(content),
            "diff": "",
            "message": "no changes (old_text == new_text)",
            "old_content": content,
            "new_content": content,
        }
    new_content = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
    replacements = count if replace_all else 1
    diff = "\n".join(
        difflib.unified_diff(
            content.splitlines(),
            new_content.splitlines(),
            fromfile=str(path),
            tofile=str(path),
            lineterm="",
        )
    )
    return {
        "ok": True,
        "path": str(path),
        "replacements": replacements,
        "bytes_before": len(content),
        "bytes_after": len(new_content),
        "diff": diff,
        "old_content": content,
        "new_content": new_content,
    }



def create_preview(path: Path, old_text: str, new_text: str, *, replace_all: bool) -> dict[str, Any]:
    preview = build_edit_preview(path, old_text, new_text, replace_all=replace_all)
    if not preview.get("ok"):
        return preview
    if preview.get("replacements") == 0:
        return preview
    now = time.time()
    with _LOCK:
        _cleanup_state(now)
        preview_id = uuid.uuid4().hex[:12]
        _PREVIEWS[preview_id] = {
            **preview,
            "created_at_ts": now,
            "replace_all": replace_all,
            "path_obj": str(path),
        }
    return {
        "ok": True,
        "preview": True,
        "preview_id": preview_id,
        "path": preview["path"],
        "replacements": preview["replacements"],
        "bytes_before": preview["bytes_before"],
        "bytes_after": preview["bytes_after"],
        "diff": preview["diff"],
        "expires_in_s": _PREVIEW_TTL_S,
    }



def apply_preview(preview_id: str) -> dict[str, Any]:
    now = time.time()
    with _LOCK:
        _cleanup_state(now)
        preview = _PREVIEWS.get(preview_id)
        if not preview:
            return {"ok": False, "error": "preview not found or expired", "status": 404}
    path = Path(preview["path"])
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"ok": False, "error": "file not found", "status": 404}
    except PermissionError:
        return {"ok": False, "error": "permission denied", "status": 403}
    except UnicodeDecodeError:
        return {"ok": False, "error": "file is not valid utf-8 (binary file)", "status": 400}
    if current != preview["old_content"]:
        return {"ok": False, "error": "file changed since preview; create a new preview first", "status": 409}
    path.write_text(preview["new_content"], encoding="utf-8")
    rollback_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _cleanup_state(now)
        _ROLLBACKS[rollback_id] = {
            "created_at_ts": now,
            "path": str(path),
            "old_content": preview["old_content"],
            "new_content": preview["new_content"],
            "preview_id": preview_id,
        }
        _PREVIEWS.pop(preview_id, None)
    return {
        "ok": True,
        "applied": True,
        "preview_id": preview_id,
        "rollback_id": rollback_id,
        "path": str(path),
        "replacements": preview["replacements"],
        "bytes": len(preview["new_content"]),
        "rollback_expires_in_s": _ROLLBACK_TTL_S,
    }



def rollback_change(rollback_id: str, *, force: bool = False) -> dict[str, Any]:
    now = time.time()
    with _LOCK:
        _cleanup_state(now)
        rollback = _ROLLBACKS.get(rollback_id)
        if not rollback:
            return {"ok": False, "error": "rollback not found or expired", "status": 404}
    path = Path(rollback["path"])
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"ok": False, "error": "file not found", "status": 404}
    except PermissionError:
        return {"ok": False, "error": "permission denied", "status": 403}
    except UnicodeDecodeError:
        return {"ok": False, "error": "file is not valid utf-8 (binary file)", "status": 400}
    if not force and current != rollback["new_content"]:
        return {"ok": False, "error": "file changed since apply; use force=true to restore anyway", "status": 409}
    path.write_text(rollback["old_content"], encoding="utf-8")
    with _LOCK:
        _ROLLBACKS.pop(rollback_id, None)
    return {
        "ok": True,
        "rolled_back": True,
        "rollback_id": rollback_id,
        "path": str(path),
        "bytes": len(rollback["old_content"]),
    }
