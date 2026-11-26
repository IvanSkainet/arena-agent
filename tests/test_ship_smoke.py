"""v4.137.0 -- Real Machine Smoke Matrix."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_ship import handle_ship_tool  # noqa: E402
from arena.ship import linux_flight, smoke as S, status as ship_status  # noqa: E402

RECORDS = "*-ship-smoke.json"
HOME_VARIABLE = "ARENA_AGENT_HOME"


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_ship_smoke_tools_registered_and_safe():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"ship.smoke", "ship.smoke_history"} <= names
    assert classify_tool_risk("ship.smoke") == "safe"
    assert classify_tool_risk("ship.smoke_history") == "safe"


@pytest.fixture(name="quiet_ship")
def _quiet_ship(monkeypatch, tmp_path):
    """A low-risk ship in a home of its own whose probes all answer at once; returns the home."""
    monkeypatch.setenv(HOME_VARIABLE, str(tmp_path))
    monkeypatch.setattr(S._posture, "get_posture", lambda: {"ok": True, "risk": "low"})
    monkeypatch.setattr(S._posture, "load_posture", lambda: {"risk": "low", "runtime": "any"})
    _stub_smoke_deps(monkeypatch)
    return tmp_path


@pytest.mark.usefixtures("quiet_ship")
def test_ship_smoke_shape():
    before_paths = {row["path"] for row in S.history(limit=100)["records"]}

    out = S.run()
    assert out["ok"] is True
    assert out["mode"] == "nominal"
    report_path = Path(out["report_path"])
    assert report_path.exists()

    # One run, one record. Each new record is shown with the second its run
    # started in: the same second twice is a double write, another second is
    # another run (#555).
    records = S.history(limit=100)["records"]
    new = [(row["path"], row["started_at"]) for row in records if row["path"] not in before_paths]
    assert new == [(str(report_path), out["started_at"])]


def test_a_run_writes_its_record_into_the_home_it_started_in(monkeypatch, quiet_ship):
    changed_to = quiet_ship / "changed-to"

    def registry_while_the_home_changes():
        monkeypatch.setenv(HOME_VARIABLE, str(changed_to))
        return {"ok": True, "count": 0, "servers": []}

    monkeypatch.setattr(S, "_mcp_registry", registry_while_the_home_changes)

    out = S.run()

    written = [path.name for path in (quiet_ship / "flight-records").glob(RECORDS)]
    assert written == [Path(out["report_path"]).name]
    assert not list(changed_to.rglob(RECORDS))


@pytest.mark.usefixtures("quiet_ship")
@pytest.mark.parametrize("on_linux", [True, False])
def test_the_linux_flight_check_is_made_only_on_linux(monkeypatch, on_linux):
    monkeypatch.setattr(S, "_on_linux", lambda: on_linux)
    monkeypatch.setattr(linux_flight, "status", lambda: {"ok": True, "mode": "nominal"})

    out = S.run()

    assert ("ship.linux_flight_check" in [check["name"] for check in out["checks"]]) is on_linux
    assert (out["proofs"]["linux_flight"] is not None) is on_linux


def test_on_linux_answers_for_the_machine_the_test_runs_on():
    assert S._on_linux() is sys.platform.startswith("linux")


def test_ship_smoke_mcp_tool(monkeypatch):
    monkeypatch.setattr(S, "run", lambda: {"ok": True, "mode": "nominal"})
    monkeypatch.setattr(S, "history", lambda limit=20: {"ok": True, "count": limit})
    assert _parsed(handle_ship_tool("ship.smoke", {}, ctx=object()))["mode"] == "nominal"
    assert _parsed(handle_ship_tool("ship.smoke_history", {"limit": 3}, ctx=object()))["count"] == 3


def _stub_smoke_deps(monkeypatch):
    monkeypatch.setattr(S, "_code_smoke", lambda: {"ok": True, "run": {"sandbox_action": "test"}, "artifact_read": {"ok": True, "path": "out/x.json"}})
    monkeypatch.setattr(S.runtimes, "probe", lambda: {"ok": True, "runtimes": {}})
    monkeypatch.setattr(S.runtime_compat, "build", lambda rt: {"ok": True, "matrix": []})
    monkeypatch.setattr(S.mobile_preflight, "preflight", lambda: {"ok": True, "ready": True, "mode": "nominal"})
    monkeypatch.setattr(S.autostart_doctor, "status", lambda: {"ok": True, "healthy": True})
    monkeypatch.setattr(S.post_update_smoke, "status", lambda: {"ok": True, "pending": False, "last": None})
    monkeypatch.setattr(S, "_mcp_registry", lambda: {"ok": True, "count": 0, "servers": []})
    # The two probes of the ship itself take seconds on a real machine and
    # answer for that machine; a report's shape does not need them.
    monkeypatch.setattr(ship_status, "status", lambda: {"ok": True})
    monkeypatch.setattr(ship_status, "preflight", lambda: {"ok": True, "mode": "nominal"})
    monkeypatch.setattr(S, "_on_linux", lambda: False)


def test_ship_smoke_armed_critical_is_not_blocked(monkeypatch, tmp_path):
    """v4.148.0: a critical (operator-authorized) posture must read as armed,
    not as a hard failure that blocks the smoke (regression for the old
    posture.not_critical check)."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(S._posture, "get_posture", lambda: {"ok": True, "risk": "critical"})
    monkeypatch.setattr(S._posture, "load_posture", lambda: {"risk": "critical", "runtime": "any"})
    _stub_smoke_deps(monkeypatch)
    out = S.run()
    assert out["ok"] is True
    assert out["mode"] == "armed"
    assert not out["failed"]
    names = [c["name"] for c in out["checks"]]
    assert "posture.known" in names and "posture.armed" in names
    assert "posture.not_critical" not in names


def test_ship_smoke_unknown_risk_is_blocked(monkeypatch, tmp_path):
    """An unknown/invalid posture still blocks the smoke (only nominal/armed pass)."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(S._posture, "get_posture", lambda: {"ok": True, "risk": "unknown"})
    monkeypatch.setattr(S._posture, "load_posture", lambda: {"risk": "unknown", "runtime": "any"})
    _stub_smoke_deps(monkeypatch)
    out = S.run()
    assert out["ok"] is False
    assert out["mode"] == "blocked"
    assert any(c["name"] == "posture.known" and not c["ok"] for c in out["failed"])
