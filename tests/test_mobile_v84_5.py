"""Tests for v3.84.5: transport fallback (USB <-> wireless ADB).

The registry + circuit breaker + routing decisions are pure Python and
can be tested without a phone. The `transport.enable_tcp` end-to-end
path talks to `adb.run` (spawns subprocess); tests here monkeypatch
that boundary so no ADB process ever starts.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Every test runs against a clean module-wide registry."""
    from arena.mobile import adb_fallback as fb
    fb.reset()
    yield
    fb.reset()


@pytest.fixture(autouse=True)
def _fake_adb_available(monkeypatch):
    """The transport helpers gate on adb presence; pretend it's there
    for every test so we exercise the routing logic, not the guard."""
    import arena.mobile.adb as _adb
    import arena.mobile.transport as _tr
    monkeypatch.setattr(_adb, "find_adb", lambda: "/fake/adb")
    monkeypatch.setattr(_tr, "find_adb", lambda: "/fake/adb")
    yield


# ---------------------------------------------------------------------------
# Registry basics
# ---------------------------------------------------------------------------
def test_pick_transport_returns_serial_when_nothing_registered():
    from arena.mobile import adb_fallback as fb
    assert fb.pick_transport("2200ad3b") == "2200ad3b"


def test_register_is_idempotent_and_adds_primary_transport():
    from arena.mobile import adb_fallback as fb
    fb.register("2200ad3b")
    fb.register("2200ad3b")
    snap = fb.snapshot("2200ad3b")
    assert len(snap) == 1
    assert len(snap[0]["transports"]) == 1
    assert snap[0]["transports"][0]["address"] == "2200ad3b"
    assert snap[0]["transports"][0]["kind"] == "usb"


def test_add_alias_appends_wireless_transport():
    from arena.mobile import adb_fallback as fb
    fb.register("2200ad3b")
    fb.add_alias("2200ad3b", "192.168.50.181:5555")
    snap = fb.snapshot("2200ad3b")[0]
    assert [t["address"] for t in snap["transports"]] == [
        "2200ad3b", "192.168.50.181:5555",
    ]
    assert snap["transports"][1]["kind"] == "tcp"


def test_add_alias_is_idempotent_and_never_shadows_primary():
    from arena.mobile import adb_fallback as fb
    fb.register("2200ad3b")
    fb.add_alias("2200ad3b", "2200ad3b")  # would duplicate primary
    fb.add_alias("2200ad3b", "192.168.50.181:5555")
    fb.add_alias("2200ad3b", "192.168.50.181:5555")
    snap = fb.snapshot("2200ad3b")[0]
    assert [t["address"] for t in snap["transports"]] == [
        "2200ad3b", "192.168.50.181:5555",
    ]


def test_drop_alias_removes_only_the_named_alias():
    from arena.mobile import adb_fallback as fb
    fb.register("2200ad3b")
    fb.add_alias("2200ad3b", "192.168.50.181:5555")
    assert fb.drop_alias("2200ad3b", "192.168.50.181:5555") is True
    assert fb.drop_alias("2200ad3b", "nope") is False
    snap = fb.snapshot("2200ad3b")[0]
    assert [t["address"] for t in snap["transports"]] == ["2200ad3b"]


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
def test_offline_stderr_trips_circuit_breaker_after_three_hits():
    from arena.mobile import adb_fallback as fb
    fb.register("2200ad3b")
    fb.add_alias("2200ad3b", "192.168.50.181:5555")

    # First 2 offline events: still healthy.
    for _ in range(2):
        fb.record_outcome("2200ad3b", "2200ad3b",
                          returncode=1, stderr="adb: device offline")
    assert fb.pick_transport("2200ad3b") == "2200ad3b"

    # Third failure trips the breaker for the primary.
    fb.record_outcome("2200ad3b", "2200ad3b",
                      returncode=1, stderr="adb: device offline")
    assert fb.pick_transport("2200ad3b") == "192.168.50.181:5555"

    snap = fb.snapshot("2200ad3b")[0]
    assert snap["failovers"] >= 1
    assert snap["transports"][0]["healthy"] is False
    assert snap["transports"][0]["consecutive_fails"] == 3
    assert snap["transports"][0]["cooldown_remaining_sec"] > 0
    assert snap["transports"][1]["healthy"] is True


def test_successful_call_resets_consecutive_fails():
    from arena.mobile import adb_fallback as fb
    fb.register("2200ad3b")
    fb.record_outcome("2200ad3b", "2200ad3b",
                      returncode=1, stderr="adb: device offline")
    fb.record_outcome("2200ad3b", "2200ad3b",
                      returncode=0, stderr="")
    snap = fb.snapshot("2200ad3b")[0]
    assert snap["transports"][0]["consecutive_fails"] == 0
    assert snap["transports"][0]["healthy"] is True
    assert snap["transports"][0]["total_calls"] == 2
    assert snap["transports"][0]["total_fails"] == 1


def test_non_offline_error_does_not_trip_the_breaker():
    from arena.mobile import adb_fallback as fb
    fb.register("2200ad3b")
    # e.g. `am start` exit 1 with a real user-facing error
    for _ in range(10):
        fb.record_outcome("2200ad3b", "2200ad3b",
                          returncode=1, stderr="Error: activity not found")
    snap = fb.snapshot("2200ad3b")[0]
    assert snap["transports"][0]["consecutive_fails"] == 0
    assert snap["transports"][0]["healthy"] is True


def test_pick_transport_returns_primary_when_all_transports_unhealthy():
    from arena.mobile import adb_fallback as fb
    fb.register("2200ad3b")
    fb.add_alias("2200ad3b", "192.168.50.181:5555")
    # Trip both.
    for addr in ("2200ad3b", "192.168.50.181:5555"):
        for _ in range(3):
            fb.record_outcome("2200ad3b", addr,
                              returncode=1, stderr="device offline")
    # Router still returns *something* -- the primary -- so callers
    # get the underlying error verbatim instead of a mysterious blank.
    assert fb.pick_transport("2200ad3b") == "2200ad3b"


def test_looks_offline_classifier_matches_known_error_shapes():
    from arena.mobile import adb_fallback as fb
    assert fb.looks_offline("adb: device offline", 1) is True
    assert fb.looks_offline("adb: device '2200ad3b' not found", 1) is True
    assert fb.looks_offline("adb: device still authorizing", 1) is True
    # returncode 0 always wins -- healthy no matter what stderr says.
    assert fb.looks_offline("adb: device offline", 0) is False
    # Unknown shape -> not tripped.
    assert fb.looks_offline("Something else went wrong", 1) is False


# ---------------------------------------------------------------------------
# Transport helper (transport.enable_tcp end-to-end with mocked adb.run)
# ---------------------------------------------------------------------------
class _FakeCP:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def test_enable_tcp_registers_alias_after_successful_probe(monkeypatch):
    from arena.mobile import transport as tr
    from arena.mobile import adb_fallback as fb

    call_log = []

    def _fake_run(argv, *, serial=None, timeout=None, **_):
        call_log.append(("adb", tuple(argv), serial))
        if "tcpip" in argv:
            return _FakeCP(0, "restarting in TCP mode port: 5555", "")
        if argv[:2] == ["shell", "ip"]:
            return _FakeCP(0, "    inet 192.168.50.181/24 brd 192.168.50.255", "")
        if argv[0] == "connect":
            return _FakeCP(0, "connected to 192.168.50.181:5555", "")
        return _FakeCP(0, "", "")

    monkeypatch.setattr(tr, "run", _fake_run)
    r = tr.enable_tcp("2200ad3b")
    assert r["ok"] is True
    assert r["alias"] == "192.168.50.181:5555"
    # Registry now has the alias attached to canonical.
    snap = fb.snapshot("2200ad3b")[0]
    assert [t["address"] for t in snap["transports"]] == [
        "2200ad3b", "192.168.50.181:5555",
    ]


def test_enable_tcp_reports_stage_when_ip_probe_fails(monkeypatch):
    from arena.mobile import transport as tr

    def _fake_run(argv, *, serial=None, timeout=None, **_):
        if "tcpip" in argv:
            return _FakeCP(0, "restarting in TCP mode port: 5555", "")
        if argv[:2] == ["shell", "ip"]:
            return _FakeCP(1, "", "Device not found")
        return _FakeCP(0, "", "")

    monkeypatch.setattr(tr, "run", _fake_run)
    r = tr.enable_tcp("2200ad3b")
    assert r["ok"] is False
    assert "wifi IP" in r["error"]
    assert any(s["stage"] == "probe_ip" for s in r["stages"])


def test_enable_tcp_skips_probe_when_host_is_provided(monkeypatch):
    from arena.mobile import transport as tr
    from arena.mobile import adb_fallback as fb

    def _fake_run(argv, *, serial=None, timeout=None, **_):
        if argv[0] == "connect":
            assert argv[1] == "10.20.30.40:5555"
            return _FakeCP(0, "connected to 10.20.30.40:5555", "")
        return _FakeCP(0, "", "")

    monkeypatch.setattr(tr, "run", _fake_run)
    r = tr.enable_tcp("2200ad3b", host="10.20.30.40", port=5555)
    assert r["ok"] is True
    assert r["alias"] == "10.20.30.40:5555"
    assert fb.pick_transport("2200ad3b") in ("2200ad3b", "10.20.30.40:5555")


def test_disable_tcp_drops_alias_and_disconnects(monkeypatch):
    from arena.mobile import transport as tr
    from arena.mobile import adb_fallback as fb

    fb.register("2200ad3b")
    fb.add_alias("2200ad3b", "192.168.50.181:5555")

    disconnected = []

    def _fake_run(argv, *, serial=None, timeout=None, **_):
        if argv[0] == "disconnect":
            disconnected.append(argv[1])
        return _FakeCP(0, "", "")

    monkeypatch.setattr(tr, "run", _fake_run)
    r = tr.disable_tcp("2200ad3b")
    assert r["ok"] is True
    assert r["dropped"] == ["192.168.50.181:5555"]
    assert disconnected == ["192.168.50.181:5555"]
    snap = fb.snapshot("2200ad3b")[0]
    assert [t["address"] for t in snap["transports"]] == ["2200ad3b"]


def test_describe_reports_active_transport_and_multi_flag():
    from arena.mobile import transport as tr
    from arena.mobile import adb_fallback as fb
    fb.register("2200ad3b")
    fb.add_alias("2200ad3b", "192.168.50.181:5555")
    d = tr.describe("2200ad3b")
    assert d["ok"] is True
    dev = d["devices"][0]
    assert dev["is_multi_transport"] is True
    assert dev["active_transport"] == "2200ad3b"


def test_parse_hostport_rejects_junk():
    from arena.mobile.transport import parse_hostport
    assert parse_hostport("192.168.1.5:5555") == ("192.168.1.5", 5555)
    assert parse_hostport("192.168.1.5:0") is None
    assert parse_hostport("192.168.1.5:99999") is None
    assert parse_hostport("localhost:5555") is None  # IPv4 only for now
    assert parse_hostport("garbage") is None
    assert parse_hostport("") is None


# ---------------------------------------------------------------------------
# adb.run must route through the registry and record outcomes.
# ---------------------------------------------------------------------------
def test_adb_run_routes_through_registry_and_records_outcome(monkeypatch):
    """When a serial has an alias, adb.run swaps the serial arg over to
    the alias once the primary trips the breaker."""
    from arena.mobile import adb as adb_mod
    from arena.mobile import adb_fallback as fb

    fb.register("2200ad3b")
    fb.add_alias("2200ad3b", "192.168.50.181:5555")
    # Trip the primary.
    for _ in range(3):
        fb.record_outcome("2200ad3b", "2200ad3b",
                          returncode=1, stderr="device offline")

    seen: dict[str, list] = {"cmd": []}

    def _fake_subprocess_run(cmd, **_):
        seen["cmd"].append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(adb_mod, "find_adb", lambda: "/fake/adb")
    monkeypatch.setattr(adb_mod.subprocess, "run", _fake_subprocess_run)
    r = adb_mod.run(["shell", "echo", "hi"], serial="2200ad3b")
    assert r.returncode == 0
    # The subprocess was invoked with the ALIAS, not the primary.
    assert seen["cmd"][0][1:3] == ["-s", "192.168.50.181:5555"]
    # Outcome (success) is recorded against the alias -> alias stays healthy.
    snap = fb.snapshot("2200ad3b")[0]
    alias_row = next(t for t in snap["transports"]
                     if t["address"] == "192.168.50.181:5555")
    assert alias_row["total_calls"] >= 1
    assert alias_row["healthy"] is True


def test_adb_run_without_serial_never_touches_registry(monkeypatch):
    from arena.mobile import adb as adb_mod
    from arena.mobile import adb_fallback as fb

    monkeypatch.setattr(adb_mod, "find_adb", lambda: "/fake/adb")
    monkeypatch.setattr(adb_mod.subprocess, "run",
                        lambda cmd, **_: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    adb_mod.run(["devices"])
    # Registry has never seen anything.
    assert fb.snapshot() == []


# ---------------------------------------------------------------------------
# Handler dataclass surface bumps to 52 fields.
# ---------------------------------------------------------------------------
def test_mobile_handlers_dataclass_fields_v84_5():
    from arena.mobile.handlers import MobileHandlers
    fields = {f.name for f in MobileHandlers.__dataclass_fields__.values()}
    for new in ("transport_status", "transport_tcp_enable",
                "transport_tcp_disable"):
        assert new in fields, f"missing new v3.84.5 handler {new}"
    assert len(fields) == 52
