"""Book of Eternity (BoE) game relay and session protocol engine.

Bridges between the Book of Eternity Game Master daemon (ConPTY / named pipe /
file protocol) and AI Agents (Arena.ai Agent Mode, Claude Code, Codex, local agents).

Security & Invariants:
1. Sandboxed to the active game_session directory.
2. Prohibits writes to client-owned paths (input/, pending_turn_snapshot*, gm_bridge_status.json).
3. Enforces realm-aware path isolation (Mortal vs Chaos Sea / Shining Abode).
4. Enforces UTF-8 JSON serialization with atomic replacement.
5. Provides fail-closed terminal signal generation (Complete-BoeTurn / Fail-BoeTurn / Complete-BoeValidationRepair).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

# Relative paths inside a game_session directory
INBOX_FILE = Path("game_state") / "control" / "arena_relay_inbox.json"
READY_COMPLETE_FILE = Path("ready") / "turn_complete.json"
READY_ERROR_FILE = Path("ready") / "turn_error.json"
REPAIR_READY_CONTROL_FILE = Path("game_state") / "control" / "validation_repair_ready.json"
REPAIR_READY_ROOT_FILE = Path("validation_repair_ready.json")
REPAIR_READY_FILE = REPAIR_READY_ROOT_FILE
TURN_REQUEST_FILE = Path("input") / "turn_request.json"
REPAIR_REQUEST_FILE = Path("game_state") / "control" / "validation_repair_request.json"
SOUL_STATE_FILE = Path("game_state") / "meta" / "soul_state.json"

# Paths that AI GM must NEVER write directly (owned by player/client/daemon)
CLIENT_OWNED_PREFIXES = (
    "input",
    "pending_turn_snapshot",
    "game_state/control/pending_turn_snapshot",
    "game_state/control/validation_repair_request.json",
    "game_state/control/validation_auto_rollback_report.json",
    "game_state/control/terminal_protocol_failure_request.json",
    "game_state/control/gm_bridge_status.json",
    "game_state/history/chat_log.json",
    "gm_bridge_status.json",
    "stories",
)

# Mortal World profile prefixes forbidden in Afterlife turns (Chaos Sea / Shining Abode)
MORTAL_WORLD_PROFILE_PREFIXES = (
    "game_state/world",
    "game_state/npcs",
    "game_state/factions",
    "game_state/player",
    "game_state/inventory",
    "game_state/combat",
    "game_state/quests",
)

# Afterlife profile prefixes forbidden in Mortal World turns
AFTERLIFE_PROFILE_PREFIXES = (
    "game_state/meta/guardians.json",
    "game_state/meta/guardian_projects.json",
    "game_state/meta/shining_abode_state.json",
    "game_state/meta/afterlife_chronicles.json",
    "game_state/meta/afterlife_spiritual_conflict_state.json",
    "game_state/meta/afterlife_entity_profiles.json",
    "game_state/meta/afterlife_lore.json",
    "game_state/meta/afterlife_active_threats.json",
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def resolve_session_path(session_dir: Path, rel_path: str | Path) -> Path:
    """Resolve and validate that a relative path stays within session_dir."""
    base = session_dir.resolve()
    target = (base / rel_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise PermissionError(f"Path escape rejected: {rel_path} escapes {session_dir}")
    return target


def is_client_owned_path(rel_path: str | Path) -> bool:
    """Return True if rel_path targets client-owned directories/files."""
    norm = str(rel_path).replace("\\", "/").strip("/").lower()
    for prefix in CLIENT_OWNED_PREFIXES:
        p_norm = prefix.lower()
        if norm == p_norm or norm.startswith(f"{p_norm}/") or norm.startswith(p_norm):
            return True
    return False


def validate_realm_path(rel_path: str | Path, current_realm: str | None) -> None:
    """Enforce realm boundary isolation against wrong-realm mutations."""
    if not current_realm:
        return
    norm = str(rel_path).replace("\\", "/").strip("/").lower()
    realm_clean = current_realm.strip().lower()

    if realm_clean in ("chaos sea", "shining abode", "afterlife"):
        for mortal_prefix in MORTAL_WORLD_PROFILE_PREFIXES:
            if norm == mortal_prefix or norm.startswith(f"{mortal_prefix}/"):
                raise PermissionError(
                    f"Wrong-realm mutation rejected: Cannot write Mortal file '{rel_path}' while in realm '{current_realm}'"
                )
    elif realm_clean in ("mortal", "mortal world", "living"):
        for afterlife_prefix in AFTERLIFE_PROFILE_PREFIXES:
            if norm == afterlife_prefix or norm.startswith(f"{afterlife_prefix}/"):
                raise PermissionError(
                    f"Wrong-realm mutation rejected: Cannot write Afterlife file '{rel_path}' while in realm '{current_realm}'"
                )


def safe_write_json(
    session_dir: Path,
    rel_path: str | Path,
    data: Any,
    *,
    current_realm: str | None = None,
) -> Path:
    """Atomic, safe write of UTF-8 JSON within the game session directory."""
    if is_client_owned_path(rel_path):
        raise PermissionError(f"Write to client-owned path {rel_path} is forbidden")

    validate_realm_path(rel_path, current_realm)

    target = resolve_session_path(session_dir, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    # Atomic write via tempfile in the same directory
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp_boe_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(target))
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
    return target


def read_turn_request(session_dir: Path) -> dict[str, Any] | None:
    """Read the active turn request written by the client runtime."""
    target = resolve_session_path(session_dir, TURN_REQUEST_FILE)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def read_repair_request(session_dir: Path) -> dict[str, Any] | None:
    """Read the active validation repair request if the turn was rejected."""
    target = resolve_session_path(session_dir, REPAIR_REQUEST_FILE)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def parse_prompt_metadata(prompt: str) -> dict[str, Any]:
    """Extract turn metadata (turnNumber, requestId, sessionId, kind) from prompt text."""
    meta: dict[str, Any] = {
        "kind": "turn",
        "turnNumber": None,
        "requestId": None,
        "sessionId": None,
    }
    # Detect prompt kind
    prompt_upper = prompt.upper()
    if "REPAIR MODE" in prompt_upper or "VALIDATION REPAIR" in prompt_upper:
        meta["kind"] = "repair"
    elif "BOOTSTRAP" in prompt_upper or "INIT" in prompt_upper:
        meta["kind"] = "bootstrap"
    elif "TERMINAL_PROTOCOL_FAILURE" in prompt_upper or "FAILURE" in prompt_upper:
        meta["kind"] = "terminal_failure"

    # Extract turnNumber: "turn #42", "turnNumber: 42", "turnNumber=42"
    m_turn = re.search(r"(?:turn\s*#|turnNumber[:=]\s*)(\d+)", prompt, re.IGNORECASE)
    if m_turn:
        meta["turnNumber"] = int(m_turn.group(1))

    # Extract requestId
    m_req = re.search(r"requestId[:=]\s*([a-zA-Z0-9_\-\.]+)", prompt, re.IGNORECASE)
    if m_req:
        meta["requestId"] = m_req.group(1).strip()

    # Extract sessionId
    m_sess = re.search(r"sessionId[:=]\s*([a-zA-Z0-9_\-\.]+)", prompt, re.IGNORECASE)
    if m_sess:
        meta["sessionId"] = m_sess.group(1).strip()

    return meta


def write_inbox(
    session_dir: Path,
    prompt: str,
    *,
    kind: str | None = None,
    turn_number: int | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Write a new prompt packet from the daemon into the relay inbox."""
    parsed = parse_prompt_metadata(prompt)
    packet = {
        "schemaVersion": 1,
        "status": "pending",
        "kind": kind or parsed["kind"],
        "receivedAtUtc": _now_iso(),
        "turnNumber": turn_number if turn_number is not None else parsed["turnNumber"],
        "requestId": request_id if request_id is not None else parsed["requestId"],
        "sessionId": session_id if session_id is not None else parsed["sessionId"],
        "prompt": prompt,
    }
    safe_write_json(session_dir, INBOX_FILE, packet)
    return packet


def read_inbox(session_dir: Path) -> dict[str, Any] | None:
    """Read the current packet from the relay inbox."""
    inbox_path = resolve_session_path(session_dir, INBOX_FILE)
    if not inbox_path.exists():
        return None
    try:
        content = json.loads(inbox_path.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            return content
    except Exception:
        return None
    return None


def wait_for_inbox(session_dir: Path, timeout_sec: float = 25.0, poll_interval: float = 0.5) -> dict[str, Any] | None:
    """Long-poll until a pending inbox turn packet is available."""
    t_end = time.time() + max(0.1, timeout_sec)
    while time.time() < t_end:
        packet = read_inbox(session_dir)
        if packet and packet.get("status") == "pending":
            return packet
        time.sleep(poll_interval)
    return None


def complete_turn(
    session_dir: Path,
    *,
    session_id: str | None = None,
    request_id: str | None = None,
    turn_number: int | None = None,
    files_modified: list[str] | None = None,
    summary: str = "Turn completed successfully",
    state_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate ready/turn_complete.json with full BoE specification metadata."""
    turn_req = read_turn_request(session_dir) or {}
    inbox = read_inbox(session_dir) or {}

    s_id = session_id or turn_req.get("sessionId") or inbox.get("sessionId") or "unknown_session"
    r_id = request_id or turn_req.get("requestId") or inbox.get("requestId") or "unknown_request"
    t_num = turn_number if turn_number is not None else turn_req.get("turnNumber", inbox.get("turnNumber", 0))

    # Clean default files modified list required by BoE contract validator
    files = list(files_modified) if files_modified else [
        "output/narrative_response.json",
        "output/debug_logs.json",
        "output/interface_updates.json",
    ]

    now_ts = _now_iso()
    complete_payload = {
        "schemaVersion": 1,
        "status": "success",
        "sessionId": s_id,
        "requestId": r_id,
        "turnNumber": t_num,
        "timestamp": now_ts,
        "completedAtUtc": now_ts,
        "filesModified": files,
        "summary": summary,
        "stateUpdates": state_updates or {},
    }

    # Remove any conflicting error signal
    err_path = resolve_session_path(session_dir, READY_ERROR_FILE)
    if err_path.exists():
        try:
            err_path.unlink()
        except OSError:
            pass

    # Write ready file
    safe_write_json(session_dir, READY_COMPLETE_FILE, complete_payload)

    # Mark inbox as completed
    if inbox:
        inbox["status"] = "completed"
        inbox["completedAtUtc"] = complete_payload["completedAtUtc"]
        safe_write_json(session_dir, INBOX_FILE, inbox)

    return complete_payload


def fail_turn(
    session_dir: Path,
    *,
    error_message: str,
    session_id: str | None = None,
    request_id: str | None = None,
    turn_number: int | None = None,
) -> dict[str, Any]:
    """Generate ready/turn_error.json to signal terminal error for the turn."""
    turn_req = read_turn_request(session_dir) or {}
    inbox = read_inbox(session_dir) or {}

    s_id = session_id or turn_req.get("sessionId") or inbox.get("sessionId") or "unknown_session"
    r_id = request_id or turn_req.get("requestId") or inbox.get("requestId") or "unknown_request"
    t_num = turn_number if turn_number is not None else turn_req.get("turnNumber", inbox.get("turnNumber", 0))

    now_ts = _now_iso()
    error_payload = {
        "schemaVersion": 1,
        "status": "error",
        "sessionId": s_id,
        "requestId": r_id,
        "turnNumber": t_num,
        "timestamp": now_ts,
        "failedAtUtc": now_ts,
        "error": error_message,
    }

    # Remove any conflicting complete signal
    comp_path = resolve_session_path(session_dir, READY_COMPLETE_FILE)
    if comp_path.exists():
        try:
            comp_path.unlink()
        except OSError:
            pass

    safe_write_json(session_dir, READY_ERROR_FILE, error_payload)

    if inbox:
        inbox["status"] = "failed"
        inbox["failedAtUtc"] = error_payload["failedAtUtc"]
        inbox["error"] = error_message
        safe_write_json(session_dir, INBOX_FILE, inbox)

    return error_payload


def repair_ready(
    session_dir: Path,
    *,
    repair_summary: str = "Validation repair applied",
    repaired_files: list[str] | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    turn_number: int | None = None,
) -> dict[str, Any]:
    """Generate validation_repair_ready.json for the daemon repair handshake."""
    repair_req = read_repair_request(session_dir) or {}
    turn_req = read_turn_request(session_dir) or {}
    inbox = read_inbox(session_dir) or {}

    s_id = session_id or repair_req.get("sessionId") or turn_req.get("sessionId") or inbox.get("sessionId") or "unknown_session"
    r_id = request_id or repair_req.get("requestId") or turn_req.get("requestId") or inbox.get("requestId") or "unknown_request"
    t_num = turn_number if turn_number is not None else repair_req.get("turnNumber", turn_req.get("turnNumber", inbox.get("turnNumber", 0)))

    now_ts = _now_iso()
    repair_payload = {
        "schemaVersion": 1,
        "status": "repaired",
        "sessionId": s_id,
        "requestId": r_id,
        "turnNumber": t_num,
        "timestamp": now_ts,
        "repairedAtUtc": now_ts,
        "summary": repair_summary,
        "repairedFiles": repaired_files or [],
    }

    # Write to canonical control location and root fallback location
    safe_write_json(session_dir, REPAIR_READY_CONTROL_FILE, repair_payload)
    safe_write_json(session_dir, REPAIR_READY_ROOT_FILE, repair_payload)

    if inbox:
        inbox["status"] = "repaired"
        inbox["repairedAtUtc"] = repair_payload["repairedAtUtc"]
        safe_write_json(session_dir, INBOX_FILE, inbox)

    return repair_payload


def get_status(session_dir: Path) -> dict[str, Any]:
    """Inspect the current state of the game session."""
    inbox = read_inbox(session_dir)
    turn_req = read_turn_request(session_dir)
    repair_req = read_repair_request(session_dir)
    ready_complete = resolve_session_path(session_dir, READY_COMPLETE_FILE).exists()
    ready_error = resolve_session_path(session_dir, READY_ERROR_FILE).exists()
    repair_file = resolve_session_path(session_dir, REPAIR_READY_CONTROL_FILE).exists() or resolve_session_path(session_dir, REPAIR_READY_ROOT_FILE).exists()
    soul_state = resolve_session_path(session_dir, SOUL_STATE_FILE).exists()

    return {
        "ok": True,
        "session_dir": str(session_dir.resolve()),
        "has_input_request": turn_req is not None,
        "has_repair_request": repair_req is not None,
        "has_soul_state": soul_state,
        "turn_request": turn_req,
        "inbox": inbox,
        "has_pending_inbox": bool(inbox and inbox.get("status") == "pending"),
        "has_ready_complete": ready_complete,
        "has_ready_error": ready_error,
        "has_repair_ready": repair_file,
    }
