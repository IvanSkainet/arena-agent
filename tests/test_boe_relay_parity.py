"""Parity test suite for Book of Eternity (BoE) relay engine, handlers, and CLI."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.game import boe_cli, boe_handlers, boe_relay  # noqa: E402


class _MockContext:
    def __init__(self, reject_auth: bool = False) -> None:
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.reject_auth = reject_auth
        self.auth_calls: list[Any] = []
        self.audit_events: list[dict[str, Any]] = []

    def require_auth(self, request: Any) -> Any:
        self.auth_calls.append(request)
        if self.reject_auth or request.headers.get("Authorization") != "Bearer t":
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        return None

    def record_request(self, *args: Any, **kwargs: Any) -> None:
        pass

    def cors_json_response(self, data: Any, status: int = 200) -> web.Response:
        return web.json_response(data, status=status)

    def audit(self, event: dict[str, Any]) -> None:
        self.audit_events.append(dict(event))


def _make_req(
    method: str,
    path: str,
    payload: Any = None,
    query: dict[str, str] | None = None,
    auth_header: str = "Bearer t",
) -> web.Request:
    headers = {"Authorization": auth_header} if auth_header else {}
    req = make_mocked_request(method, path, headers=headers)
    if query:
        req._match_info = query  # type: ignore[attr-defined]

    async def _json():
        if payload is not None:
            return payload
        return {}

    req.json = _json  # type: ignore[method-assign]
    return req


# ---------------------------------------------------------------------------
# Path & Security Tests
# ---------------------------------------------------------------------------

def test_resolve_session_path(tmp_path):
    session = tmp_path / "game_session"
    session.mkdir()
    valid = boe_relay.resolve_session_path(session, "game_state/soul_state.json")
    assert valid == session / "game_state" / "soul_state.json"

    with pytest.raises(PermissionError, match="Path escape rejected"):
        boe_relay.resolve_session_path(session, "../secret.txt")


@pytest.mark.parametrize("path,expected_blocked", [
    ("input/turn_request.json", True),
    ("input", True),
    ("pending_turn_snapshot.json", True),
    ("pending_turn_snapshot_01.json", True),
    ("gm_bridge_status.json", True),
    ("stories/log.jsonl", True),
    ("game_state/soul_state.json", False),
    ("output/turn_result.json", False),
    ("ready/turn_complete.json", False),
])
def test_is_client_owned_path(path, expected_blocked):
    assert boe_relay.is_client_owned_path(path) is expected_blocked


def test_safe_write_json(tmp_path):
    session = tmp_path / "game_session"
    session.mkdir()

    # Allowed write
    written = boe_relay.safe_write_json(session, "game_state/state.json", {"hero": "Mage", "hp": 100})
    assert written.exists()
    content = json.loads(written.read_text(encoding="utf-8"))
    assert content == {"hero": "Mage", "hp": 100}

    # Prohibited write (client-owned)
    with pytest.raises(PermissionError, match="Write to client-owned path"):
        boe_relay.safe_write_json(session, "input/turn_request.json", {"hack": True})

    # Realm-aware boundary enforcement
    with pytest.raises(PermissionError, match="Wrong-realm mutation rejected"):
        boe_relay.safe_write_json(
            session, "game_state/npcs/npc_state.json", {"npc": "Guard"}, current_realm="Chaos Sea"
        )

    with pytest.raises(PermissionError, match="Wrong-realm mutation rejected"):
        boe_relay.safe_write_json(
            session, "game_state/meta/guardians.json", {"guardians": []}, current_realm="Mortal World"
        )


def test_read_turn_and_repair_requests(tmp_path):
    session = tmp_path / "game_session"
    session.mkdir()
    input_dir = session / "input"
    input_dir.mkdir()
    control_dir = session / "game_state" / "control"
    control_dir.mkdir(parents=True)

    # Write turn_request.json directly (as client would)
    (input_dir / "turn_request.json").write_text(
        json.dumps({
            "sessionId": "sess_live_1",
            "requestId": "req_live_1",
            "turnNumber": 3,
            "playerAction": "Search the archive",
            "currentRealm": "Chaos Sea"
        }),
        encoding="utf-8"
    )

    turn_req = boe_relay.read_turn_request(session)
    assert turn_req is not None
    assert turn_req["sessionId"] == "sess_live_1"
    assert turn_req["turnNumber"] == 3

    # Write repair_request.json
    (control_dir / "validation_repair_request.json").write_text(
        json.dumps({
            "sessionId": "sess_live_1",
            "requestId": "req_live_1",
            "turnNumber": 3,
            "validationErrors": ["Missing output/narrative_response.json"]
        }),
        encoding="utf-8"
    )

    rep_req = boe_relay.read_repair_request(session)
    assert rep_req is not None
    assert rep_req["validationErrors"] == ["Missing output/narrative_response.json"]


# ---------------------------------------------------------------------------
# Prompt Parsing & Inbox Protocol
# ---------------------------------------------------------------------------

def test_parse_prompt_metadata():
    p_turn = "Process turn #42 (requestId=req_9988, sessionId=sess_123). Evaluate mortal gate."
    m_turn = boe_relay.parse_prompt_metadata(p_turn)
    assert m_turn["kind"] == "turn"
    assert m_turn["turnNumber"] == 42
    assert m_turn["requestId"] == "req_9988"
    assert m_turn["sessionId"] == "sess_123"

    p_repair = "REPAIR MODE: validation repair required for turn #15 requestId: r_55"
    m_repair = boe_relay.parse_prompt_metadata(p_repair)
    assert m_repair["kind"] == "repair"
    assert m_repair["turnNumber"] == 15
    assert m_repair["requestId"] == "r_55"

    p_boot = "BOOTSTRAP game session init"
    m_boot = boe_relay.parse_prompt_metadata(p_boot)
    assert m_boot["kind"] == "bootstrap"


def test_inbox_lifecycle_complete(tmp_path):
    session = tmp_path / "session_01"
    session.mkdir()

    # Write inbox
    packet = boe_relay.write_inbox(session, "Process turn #7 (requestId=req_07, sessionId=s_1).")
    assert packet["status"] == "pending"
    assert packet["turnNumber"] == 7

    # Read inbox
    read = boe_relay.read_inbox(session)
    assert read is not None
    assert read["turnNumber"] == 7

    # Wait for inbox
    waited = boe_relay.wait_for_inbox(session, timeout_sec=0.5)
    assert waited is not None
    assert waited["requestId"] == "req_07"

    # Complete turn
    comp = boe_relay.complete_turn(
        session,
        files_modified=["output/narrative_response.json", "output/debug_logs.json"],
        summary="Hero survived combat",
        state_updates={"hp": 90},
    )
    assert comp["status"] == "success"
    assert comp["turnNumber"] == 7
    assert comp["requestId"] == "req_07"
    assert comp["sessionId"] == "s_1"
    assert "timestamp" in comp
    assert comp["filesModified"] == ["output/narrative_response.json", "output/debug_logs.json"]

    # Verify ready file exists
    ready_file = session / boe_relay.READY_COMPLETE_FILE
    assert ready_file.exists()
    ready_data = json.loads(ready_file.read_text(encoding="utf-8"))
    assert ready_data["status"] == "success"
    assert ready_data["summary"] == "Hero survived combat"
    assert ready_data["filesModified"] == ["output/narrative_response.json", "output/debug_logs.json"]
    assert "timestamp" in ready_data

    # Inbox is updated to completed
    inbox_done = boe_relay.read_inbox(session)
    assert inbox_done["status"] == "completed"


def test_inbox_lifecycle_fail_and_repair(tmp_path):
    session = tmp_path / "session_02"
    session.mkdir()

    boe_relay.write_inbox(session, "Process turn #12 (requestId=req_12).")
    failed = boe_relay.fail_turn(session, error_message="Fatal rules violation")
    assert failed["status"] == "error"
    assert failed["error"] == "Fatal rules violation"
    assert "timestamp" in failed
    assert (session / boe_relay.READY_ERROR_FILE).exists()

    # Repair turn
    rep = boe_relay.repair_ready(session, repair_summary="Corrected schema", repaired_files=["output/debug_logs.json"])
    assert rep["status"] == "repaired"
    assert "timestamp" in rep
    assert rep["repairedFiles"] == ["output/debug_logs.json"]
    assert (session / boe_relay.REPAIR_READY_CONTROL_FILE).exists()
    assert (session / boe_relay.REPAIR_READY_ROOT_FILE).exists()


def test_get_status(tmp_path):
    session = tmp_path / "session_03"
    session.mkdir()
    st = boe_relay.get_status(session)
    assert st["ok"] is True
    assert st["has_pending_inbox"] is False
    assert st["has_ready_complete"] is False

    boe_relay.write_inbox(session, "turn #1")
    st2 = boe_relay.get_status(session)
    assert st2["has_pending_inbox"] is True


# ---------------------------------------------------------------------------
# HTTP Handlers
# ---------------------------------------------------------------------------

def test_boe_handlers_registration():
    ctx = _MockContext()
    handlers = boe_handlers.make_boe_handlers(ctx)
    expected = {
        "boe_status",
        "boe_wait_inbox",
        "boe_read_turn",
        "boe_write_json",
        "boe_complete_turn",
        "boe_fail_turn",
        "boe_repair_turn",
    }
    assert set(handlers.keys()) == expected


def test_handle_boe_status_and_read(tmp_path):
    ctx = _MockContext()
    handlers = boe_handlers.make_boe_handlers(ctx)
    session = tmp_path / "game_session"
    session.mkdir()

    req = _make_req("GET", f"/v1/game/boe/status?session_dir={session}")
    resp = asyncio.run(handlers["boe_status"](req))
    assert resp.status == 200
    body = json.loads(resp.text)
    assert body["ok"] is True
    assert body["has_pending_inbox"] is False


def test_handle_boe_wait_inbox_and_complete(tmp_path):
    ctx = _MockContext()
    handlers = boe_handlers.make_boe_handlers(ctx)
    session = tmp_path / "game_session"
    session.mkdir()

    # Pre-write inbox packet
    boe_relay.write_inbox(session, "Process turn #5 (requestId=r_5, sessionId=s_5).")

    req_wait = _make_req("POST", "/v1/game/boe/wait_inbox", {"session_dir": str(session), "timeout_sec": 1.0})
    resp_wait = asyncio.run(handlers["boe_wait_inbox"](req_wait))
    assert resp_wait.status == 200
    body_wait = json.loads(resp_wait.text)
    assert body_wait["has_packet"] is True
    assert body_wait["packet"]["turnNumber"] == 5

    # Complete turn
    req_comp = _make_req("POST", "/v1/game/boe/complete_turn", {
        "session_dir": str(session),
        "summary": "Completed through handler",
    })
    resp_comp = asyncio.run(handlers["boe_complete_turn"](req_comp))
    assert resp_comp.status == 200
    body_comp = json.loads(resp_comp.text)
    assert body_comp["ok"] is True
    assert body_comp["result"]["turnNumber"] == 5
    assert (session / boe_relay.READY_COMPLETE_FILE).exists()


def test_handle_boe_write_json_and_jail(tmp_path):
    ctx = _MockContext()
    handlers = boe_handlers.make_boe_handlers(ctx)
    session = tmp_path / "game_session"
    session.mkdir()

    # Allowed write
    req_write = _make_req("POST", "/v1/game/boe/write_json", {
        "session_dir": str(session),
        "path": "game_state/quest.json",
        "data": {"quest": "Find the Relic"},
    })
    resp_write = asyncio.run(handlers["boe_write_json"](req_write))
    assert resp_write.status == 200
    assert (session / "game_state" / "quest.json").exists()

    # Prohibited write (client-owned)
    req_blocked = _make_req("POST", "/v1/game/boe/write_json", {
        "session_dir": str(session),
        "path": "input/turn_request.json",
        "data": {"bad": True},
    })
    resp_blocked = asyncio.run(handlers["boe_write_json"](req_blocked))
    assert resp_blocked.status == 403


# ---------------------------------------------------------------------------
# CLI Helpers
# ---------------------------------------------------------------------------

def test_strip_bracketed_paste():
    raw = "\x1b[200~Process turn #10\x1b[201~"
    clean = boe_cli._strip_bracketed_paste(raw)
    assert clean == "Process turn #10"


@pytest.mark.parametrize("handler_key,method,path", [
    ("boe_status", "GET", "/v1/game/boe/status"),
    ("boe_wait_inbox", "POST", "/v1/game/boe/wait_inbox"),
    ("boe_read_turn", "GET", "/v1/game/boe/read_turn"),
    ("boe_write_json", "POST", "/v1/game/boe/write_json"),
    ("boe_complete_turn", "POST", "/v1/game/boe/complete_turn"),
    ("boe_fail_turn", "POST", "/v1/game/boe/fail_turn"),
    ("boe_repair_turn", "POST", "/v1/game/boe/repair_turn"),
])
def test_all_boe_handlers_require_auth(handler_key, method, path):
    ctx = _MockContext(reject_auth=True)
    handlers = boe_handlers.make_boe_handlers(ctx)
    req = _make_req(method, path, auth_header="")
    resp = asyncio.run(handlers[handler_key](req))
    assert resp.status == 401
    assert len(ctx.auth_calls) == 1
