"""v4.54.1 tests: retry + wait_for step-level features."""
from __future__ import annotations

import http.server
import json
import socket
import threading
import time
from pathlib import Path

import pytest

from arena.scenarios import (
    ScenarioMissionStore,
    build_scenarios_runtime,
    derive_scenario_risk,
    resolve_missions_dir,
)
from arena.scenarios.runtime import (
    _do_wait_for,
    _normalise_retry,
    _normalise_wait_for,
    _wait_for_file,
    _wait_for_http,
)


@pytest.fixture
def tmp_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    (tmp_path / "missions").mkdir(exist_ok=True)
    assert resolve_missions_dir() == tmp_path / "missions"
    return ScenarioMissionStore()


# --------------------------------------------------------------
# _normalise_retry
# --------------------------------------------------------------

def test_normalise_retry_defaults_when_missing():
    r = _normalise_retry({})
    assert r == {"attempts": 1, "delay_seconds": 0.0, "backoff": 1.0}


def test_normalise_retry_reads_spec():
    r = _normalise_retry({"retry": {"attempts": 5, "delay_seconds": 2, "backoff": 3.0}})
    assert r == {"attempts": 5, "delay_seconds": 2.0, "backoff": 3.0}


def test_normalise_retry_clamps_absurd_values():
    r = _normalise_retry({"retry": {"attempts": 999, "delay_seconds": 9999, "backoff": 100}})
    assert r["attempts"] == 10       # capped at 10 to avoid runaway loops
    assert r["delay_seconds"] == 60   # capped at 60s
    assert r["backoff"] == 5.0


def test_normalise_retry_rejects_nonsense_gracefully():
    # attempts=0 → clamped to 1 (single attempt = no retry)
    r = _normalise_retry({"retry": {"attempts": 0, "backoff": 0.1}})
    assert r["attempts"] == 1
    assert r["backoff"] >= 1.0


# --------------------------------------------------------------
# _normalise_wait_for
# --------------------------------------------------------------

def test_normalise_wait_for_none_when_missing():
    assert _normalise_wait_for({}) is None


def test_normalise_wait_for_file():
    w = _normalise_wait_for({"wait_for": {"file": "/tmp/x", "timeout_seconds": 15}})
    assert w == {"timeout_seconds": 15.0, "poll_seconds": 1.0, "file": "/tmp/x"}


def test_normalise_wait_for_http_defaults():
    w = _normalise_wait_for({"wait_for": {"http": {"url": "https://ex/status"}}})
    assert w["http"]["url"] == "https://ex/status"
    assert w["http"]["expect_status"] == 200
    assert w["http"]["method"] == "GET"


def test_normalise_wait_for_http_custom_status_and_json():
    w = _normalise_wait_for({"wait_for": {
        "http": {"url": "https://ex/status", "expect_status": 201,
                 "expect_json_field": "done", "expect_json_value": True,
                 "method": "post"},
        "timeout_seconds": 5, "poll_seconds": 0.5,
    }})
    assert w["http"]["expect_status"] == 201
    assert w["http"]["expect_json_field"] == "done"
    assert w["http"]["expect_json_value"] is True
    assert w["http"]["method"] == "POST"
    assert w["timeout_seconds"] == 5.0
    assert w["poll_seconds"] == 0.5


def test_normalise_wait_for_empty_config_returns_none():
    """`wait_for: {}` with neither file nor http = normalise to None."""
    assert _normalise_wait_for({"wait_for": {"timeout_seconds": 5}}) is None


def test_normalise_wait_for_timeouts_are_clamped():
    w = _normalise_wait_for({"wait_for": {"file": "/tmp/x",
                                          "timeout_seconds": 99999, "poll_seconds": 999}})
    assert w["timeout_seconds"] == 3600  # 1h ceiling
    assert w["poll_seconds"] == 30       # ceiling
    # Floors: timeout min 1s, poll min 0.1s.
    w2 = _normalise_wait_for({"wait_for": {"file": "/tmp/x",
                                           "timeout_seconds": 0.001, "poll_seconds": 0.001}})
    assert w2["timeout_seconds"] == 1.0
    assert w2["poll_seconds"] == 0.1


def test_normalise_wait_for_explicit_zero_hits_floor():
    """Explicit 0 gets clamped up to the minimum floor (1s / 0.1s).
    We do NOT promote 0 to the default -- 0 usually means the
    author typo'd, and the floor is a saner side-effect than 30s."""
    w = _normalise_wait_for({"wait_for": {"file": "/tmp/x",
                                          "timeout_seconds": 0, "poll_seconds": 0}})
    assert w["timeout_seconds"] == 1.0
    assert w["poll_seconds"] == 0.1


# --------------------------------------------------------------
# _wait_for_file
# --------------------------------------------------------------

def test_wait_for_file_succeeds_immediately(tmp_path):
    p = tmp_path / "note.m4a"
    p.write_bytes(b"hello")
    r = _wait_for_file(str(p), timeout=5, poll=0.1)
    assert r["ok"] is True
    assert r["path"] == str(p)
    assert r["size_bytes"] == 5


def test_wait_for_file_appears_after_delay(tmp_path):
    p = tmp_path / "note.m4a"
    def _create():
        time.sleep(0.2)
        p.write_bytes(b"x" * 42)
    threading.Thread(target=_create, daemon=True).start()
    r = _wait_for_file(str(p), timeout=5, poll=0.05)
    assert r["ok"] is True
    assert r["size_bytes"] == 42
    assert r["waited_seconds"] >= 0.15


def test_wait_for_file_times_out(tmp_path):
    r = _wait_for_file(str(tmp_path / "never"), timeout=0.5, poll=0.1)
    assert r["ok"] is False
    assert "did not appear" in r["error"]
    assert r["waited_seconds"] >= 0.4


def test_wait_for_file_expands_tilde(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    # ``os.path.expanduser`` reads HOME on POSIX and USERPROFILE on
    # Windows. Set both so this test is portable.
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    (fake_home / "note.txt").write_text("hi")
    r = _wait_for_file("~/note.txt", timeout=1, poll=0.05)
    assert r["ok"] is True


# --------------------------------------------------------------
# _wait_for_http (with a real localhost server)
# --------------------------------------------------------------

class _CountingHandler(http.server.BaseHTTPRequestHandler):
    responses: list[tuple[int, bytes]] = []  # populated per-test
    hits: list[str] = []

    def log_message(self, *a, **kw):
        pass  # silence

    def _reply(self):
        try:
            status, body = self.responses.pop(0)
        except IndexError:
            status, body = 200, b'{"done": true}'
        self.hits.append(self.path)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply()

    def do_POST(self):
        self._reply()


@pytest.fixture
def local_http():
    _CountingHandler.responses = []
    _CountingHandler.hits = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = http.server.HTTPServer(("127.0.0.1", port), _CountingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()


def test_wait_for_http_succeeds_on_first_hit(local_http):
    _CountingHandler.responses = [(200, b'{"done": true}')]
    cfg = {"url": f"{local_http}/status", "expect_status": 200,
           "expect_json_field": "", "expect_json_value": None, "method": "GET"}
    r = _wait_for_http(cfg, timeout=3, poll=0.1)
    assert r["ok"] is True
    assert r["status"] == 200


def test_wait_for_http_waits_until_status_flips(local_http):
    # First two responses 202, then 200.
    _CountingHandler.responses = [(202, b'{}'), (202, b'{}'), (200, b'{"ok":1}')]
    cfg = {"url": f"{local_http}/probe", "expect_status": 200,
           "expect_json_field": "", "expect_json_value": None, "method": "GET"}
    r = _wait_for_http(cfg, timeout=5, poll=0.2)
    assert r["ok"] is True
    assert len(_CountingHandler.hits) == 3


def test_wait_for_http_json_field_match(local_http):
    _CountingHandler.responses = [(200, b'{"done": false}'), (200, b'{"done": true}')]
    cfg = {"url": f"{local_http}/j", "expect_status": 200,
           "expect_json_field": "done", "expect_json_value": True, "method": "GET"}
    r = _wait_for_http(cfg, timeout=5, poll=0.1)
    assert r["ok"] is True
    assert len(_CountingHandler.hits) == 2


def test_wait_for_http_times_out_when_never_matches(local_http):
    _CountingHandler.responses = [(202, b'{}')] * 100
    cfg = {"url": f"{local_http}/never", "expect_status": 200,
           "expect_json_field": "", "expect_json_value": None, "method": "GET"}
    r = _wait_for_http(cfg, timeout=0.5, poll=0.1)
    assert r["ok"] is False
    assert r["status"] == 202


def test_wait_for_http_rejects_non_http_schemes():
    cfg = {"url": "file:///etc/passwd", "expect_status": 200,
           "expect_json_field": "", "expect_json_value": None, "method": "GET"}
    r = _wait_for_http(cfg, timeout=1, poll=0.1)
    assert r["ok"] is False
    assert "http/https" in r["error"]


# --------------------------------------------------------------
# derive_scenario_risk with wait_for.http
# --------------------------------------------------------------

def test_wait_for_http_promotes_to_medium():
    doc = {"steps": [{"tool": "sys.status", "wait_for": {"http": {"url": "https://x"}}}]}
    assert derive_scenario_risk(doc) == "medium"


def test_wait_for_file_does_NOT_promote():
    doc = {"steps": [{"tool": "sys.status", "wait_for": {"file": "/tmp/x"}}]}
    assert derive_scenario_risk(doc) == "safe"


def test_wait_for_http_does_not_downgrade_dangerous():
    doc = {"steps": [{"tool": "fs.write", "wait_for": {"http": {"url": "https://x"}}}]}
    assert derive_scenario_risk(doc) == "dangerous"


# --------------------------------------------------------------
# Runtime integration: retry
# --------------------------------------------------------------

def test_runtime_retry_recovers_after_flake(tmp_storage):
    tmp_storage.save("r", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status", "arguments": {},
                   "retry": {"attempts": 3, "delay_seconds": 0.01, "backoff": 1.0}}],
    }))
    attempts = {"n": 0}
    def dispatch(t, a):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return {"ok": False, "error": "flaky"}
        return {"ok": True, "value": "final"}
    rt = build_scenarios_runtime(dispatch, storage=tmp_storage)
    run = rt.run("r", approved=True)
    assert run.ok is True
    assert attempts["n"] == 3
    assert run.steps[0].result.get("attempts_used") == 3


def test_runtime_retry_all_attempts_fail(tmp_storage):
    tmp_storage.save("r", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status", "arguments": {},
                   "retry": {"attempts": 2, "delay_seconds": 0.01}}],
    }))
    calls = []
    def dispatch(t, a):
        calls.append(t)
        return {"ok": False, "error": "broken"}
    rt = build_scenarios_runtime(dispatch, storage=tmp_storage)
    run = rt.run("r", approved=True)
    assert run.ok is False
    assert len(calls) == 2
    assert run.steps[0].result.get("attempts_used") == 2


def test_runtime_no_retry_block_means_single_attempt(tmp_storage):
    tmp_storage.save("r", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status", "arguments": {}}],
    }))
    calls = []
    def dispatch(t, a):
        calls.append(t)
        return {"ok": False, "error": "no"}
    rt = build_scenarios_runtime(dispatch, storage=tmp_storage)
    run = rt.run("r", approved=True)
    assert not run.ok
    assert len(calls) == 1
    # attempts_used is not set when only 1 attempt (avoids noise).
    assert "attempts_used" not in run.steps[0].result


# --------------------------------------------------------------
# Runtime integration: wait_for.file
# --------------------------------------------------------------

def test_runtime_wait_for_file_succeeds(tmp_storage, tmp_path):
    fpath = tmp_path / "download.dat"
    tmp_storage.save("wf", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status", "arguments": {},
                   "wait_for": {"file": str(fpath), "timeout_seconds": 3, "poll_seconds": 0.05}}],
    }))
    def _create():
        time.sleep(0.2)
        fpath.write_bytes(b"data")
    threading.Thread(target=_create, daemon=True).start()
    rt = build_scenarios_runtime(lambda t, a: {"ok": True}, storage=tmp_storage)
    run = rt.run("wf", approved=True)
    assert run.ok
    assert run.steps[0].result["wait_for"]["ok"] is True
    assert run.steps[0].result["wait_for"]["kind"] == "file"


def test_runtime_wait_for_file_times_out_fails_step(tmp_storage, tmp_path):
    tmp_storage.save("wt", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status", "arguments": {},
                   # 1s is the runtime floor; anything smaller
                   # gets clamped so the assertion stays honest.
                   "wait_for": {"file": str(tmp_path / "never"),
                                "timeout_seconds": 1, "poll_seconds": 0.1}}],
    }))
    rt = build_scenarios_runtime(lambda t, a: {"ok": True}, storage=tmp_storage)
    run = rt.run("wt", approved=True)
    assert not run.ok
    assert "wait_for failed" in (run.steps[0].error or "")


def test_runtime_wait_for_http_success_end_to_end(tmp_storage, local_http):
    _CountingHandler.responses = [(200, b'{"ready": true}')]
    tmp_storage.save("wh", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status", "arguments": {},
                   "wait_for": {"http": {"url": f"{local_http}/status", "expect_status": 200},
                                "timeout_seconds": 3, "poll_seconds": 0.1}}],
    }))
    rt = build_scenarios_runtime(lambda t, a: {"ok": True}, storage=tmp_storage)
    # wait_for.http promotes to medium; needs approval.
    run = rt.run("wh", approved=True)
    assert run.ok
    assert run.steps[0].result["wait_for"]["ok"] is True


def test_runtime_wait_for_combined_with_retry(tmp_storage, tmp_path):
    """Retry loops around the tool call AND its wait_for check.

    Simulates: tool succeeds but wait_for file appears well AFTER
    the first attempt's 1-second wait timeout floor — a second
    attempt (after backoff) is the one that sees the file.
    """
    fpath = tmp_path / "delayed.dat"
    tmp_storage.save("comb", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status", "arguments": {},
                   "retry": {"attempts": 5, "delay_seconds": 0.05, "backoff": 1.0},
                   # timeout floor is 1s -- so the first attempt
                   # gives up at t=1s.
                   "wait_for": {"file": str(fpath),
                                "timeout_seconds": 1, "poll_seconds": 0.1}}],
    }))
    # File appears at t=1.3s, well after the first attempt (1s)
    # has failed and the second attempt started.
    def _create():
        time.sleep(1.3)
        fpath.write_bytes(b"ok")
    threading.Thread(target=_create, daemon=True).start()
    rt = build_scenarios_runtime(lambda t, a: {"ok": True}, storage=tmp_storage)
    run = rt.run("comb", approved=True)
    assert run.ok
    assert run.steps[0].result.get("attempts_used", 1) >= 2
