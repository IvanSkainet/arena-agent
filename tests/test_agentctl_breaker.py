"""Tests for the ``agentctl breaker`` CLI (v4.17.0).

Composition test of three earlier releases -- v4.8.0 breaker,
v4.14.0 reset endpoint, v4.16.0 breaker_summary -- exposed as
shell verbs. Uses a real http.server stub for the bridge so the
tests exercise the full HTTP path (urllib.request in the CLI's
bridge_get/bridge_post), not just imports.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_CLI = _REPO / "bin" / "agentctl"


# ---------------------------------------------------------------------------
# Fake bridge -- returns whatever we hand it
# ---------------------------------------------------------------------------
class _StubBridge:
    """Tiny HTTPServer that answers /v1/tunnels/probe,
    /v1/agent/config and /v1/tunnels/probe/reset with whatever
    payloads we injected via ``self.responses``. Records every
    request so tests can assert on side-effects."""

    def __init__(self, responses):
        self.responses = dict(responses)
        self.received: list[tuple[str, str, bytes]] = []
        self.server = None
        self.thread = None
        self.port = 0

    def start(self):
        outer = self

        class _H(BaseHTTPRequestHandler):
            def _write(self, status, body):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                outer.received.append(("GET", self.path, b""))
                resp = outer.responses.get(("GET", self.path.split("?")[0]))
                if resp is None:
                    self._write(404, {"ok": False, "error": "not found"})
                    return
                status, body = resp
                self._write(status, body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body_in = self.rfile.read(length) if length else b""
                outer.received.append(("POST", self.path, body_in))
                resp = outer.responses.get(("POST", self.path))
                if resp is None:
                    self._write(404, {"ok": False, "error": "not found"})
                    return
                status, body = resp
                self._write(status, body)

            def log_message(self, *_a, **_kw):
                pass

        # Bind to an ephemeral port so parallel tests don't clash.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.server = HTTPServer(("127.0.0.1", self.port), _H)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def stub_bridge():
    """Yield an unconfigured stub; test configures ``.responses``
    before spawning the CLI."""
    b = _StubBridge({})
    b.start()
    try:
        yield b
    finally:
        b.stop()


def _run_cli(args: list[str], bridge_url: str, extra_env=None):
    """Spawn ``bin/agentctl`` as a subprocess. Returns
    CompletedProcess. ARENA_BRIDGE_URL points at the stub;
    ARENA_BRIDGE_TOKEN is set to a stub value so the CLI's
    ``_load_token()`` doesn't try to read the real token.txt."""
    env = os.environ.copy()
    env.pop("ARENA_TOKEN_FILE", None)
    env["ARENA_BRIDGE_URL"] = bridge_url
    env["ARENA_BRIDGE_TOKEN"] = "stub-token"
    env["ARENA_AGENT_HOME"] = str(_REPO / "does-not-exist")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(_CLI)] + args,
        capture_output=True, text=True, timeout=15, env=env,
    )


# ---------------------------------------------------------------------------
# CLI help + wiring
# ---------------------------------------------------------------------------
def test_help_lists_breaker_namespace():
    """The top-level ``agentctl commands`` help must mention the
    new breaker namespace so operators discover it without reading
    the source."""
    proc = _run_cli(["commands"], bridge_url="http://127.0.0.1:1")
    assert proc.returncode == 0
    assert "breaker" in proc.stdout
    assert "status|deprio|reset" in proc.stdout


def test_breaker_help_verb_prints_usage():
    proc = _run_cli(["breaker", "help"], bridge_url="http://127.0.0.1:1")
    assert proc.returncode == 0
    for kw in ("status", "deprio", "reset", "--json", "--quiet",
               "--no-fail-open"):
        assert kw in proc.stdout, f"help missing keyword: {kw}"


# ---------------------------------------------------------------------------
# status verb
# ---------------------------------------------------------------------------
def test_status_empty_snapshot_prints_placeholder_and_exit_0(stub_bridge):
    stub_bridge.responses[("GET", "/v1/tunnels/probe")] = (
        200, {"ok": True, "priority": ["tailscale"], "probes": [],
              "breaker": {}, "reachable_count": 0}
    )
    proc = _run_cli(["breaker", "status"], stub_bridge.url())
    assert proc.returncode == 0, proc.stderr
    assert "breaker empty" in proc.stdout


def test_status_open_breaker_exits_3_and_shows_table(stub_bridge):
    """Any open record triggers the exit-3 signal so shell one-
    liners can react without parsing JSON."""
    stub_bridge.responses[("GET", "/v1/tunnels/probe")] = (
        200, {"ok": True, "priority": ["cloudflared"], "probes": [],
              "breaker": {
                  "cloudflared|foo.example:443": {
                      "state": "open", "consecutive_failures": 3,
                      "last_error": "timeout after 1.5s",
                      "cools_down_in_sec": 42.0,
                  }
              }, "reachable_count": 0}
    )
    proc = _run_cli(["breaker", "status"], stub_bridge.url())
    assert proc.returncode == 3, (
        f"expected exit 3 for open breaker, got {proc.returncode}: "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "cloudflared|foo.example:443" in proc.stdout
    assert "open" in proc.stdout
    assert "42.0s" in proc.stdout
    assert "timeout after 1.5s" in proc.stdout
    # Summary footer.
    assert "open_providers=cloudflared" in proc.stdout


def test_status_no_fail_open_flag_suppresses_exit_3(stub_bridge):
    stub_bridge.responses[("GET", "/v1/tunnels/probe")] = (
        200, {"ok": True, "breaker": {
            "cloudflared|x:1": {"state": "open",
                                "consecutive_failures": 3},
        }}
    )
    proc = _run_cli(["breaker", "status", "--no-fail-open"],
                    stub_bridge.url())
    assert proc.returncode == 0
    assert "cloudflared|x:1" in proc.stdout


def test_status_json_flag_emits_valid_json_with_summary(stub_bridge):
    stub_bridge.responses[("GET", "/v1/tunnels/probe")] = (
        200, {"ok": True, "breaker": {
            "zerotier|10.0.0.1:8765": {
                "state": "closed", "consecutive_failures": 1},
            "cloudflared|x:443": {"state": "open",
                                  "consecutive_failures": 3},
        }}
    )
    proc = _run_cli(["breaker", "status", "--json", "--no-fail-open"],
                    stub_bridge.url())
    assert proc.returncode == 0
    parsed = json.loads(proc.stdout)
    assert "breaker" in parsed
    assert "summary" in parsed
    # v4.16.0 shape.
    s = parsed["summary"]
    assert s["open"] == ["cloudflared"]
    assert s["warn"] == ["zerotier"]
    assert s["open_count"] == 1
    assert s["warn_count"] == 1
    assert s["total_records"] == 2


def test_status_quiet_suppresses_table_but_still_exits_3(stub_bridge):
    stub_bridge.responses[("GET", "/v1/tunnels/probe")] = (
        200, {"ok": True, "breaker": {"cf|x:1": {"state": "open",
                                                  "consecutive_failures": 3}}}
    )
    proc = _run_cli(["breaker", "status", "--quiet"], stub_bridge.url())
    assert proc.returncode == 3
    # No table lines.
    assert "KEY" not in proc.stdout
    assert "summary" not in proc.stdout


def test_status_bridge_unreachable_exits_1_with_stderr():
    """Non-existent bridge URL -> connection refused -> exit 1
    (network/bridge failure), NOT exit 3 (which is reserved for
    "breaker open on a working bridge")."""
    # Bind and immediately close so the port is guaranteed unused.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()
    proc = _run_cli(["breaker", "status"],
                    bridge_url=f"http://127.0.0.1:{dead_port}")
    assert proc.returncode == 1
    assert "Error contacting bridge" in proc.stderr


def test_status_bridge_ok_false_exits_1(stub_bridge):
    stub_bridge.responses[("GET", "/v1/tunnels/probe")] = (
        200, {"ok": False, "error": "internal error"}
    )
    proc = _run_cli(["breaker", "status"], stub_bridge.url())
    assert proc.returncode == 1
    assert "returned failure" in proc.stderr


# ---------------------------------------------------------------------------
# deprio verb
# ---------------------------------------------------------------------------
def test_deprio_prints_one_provider_per_line_and_exits_3(stub_bridge):
    stub_bridge.responses[("GET", "/v1/agent/config")] = (
        200, {"ok": True, "priority": ["tailscale", "zerotier", "cloudflared"],
              "deprioritized": ["cloudflared", "zerotier"],
              "breaker_summary": {}}
    )
    proc = _run_cli(["breaker", "deprio"], stub_bridge.url())
    assert proc.returncode == 3
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines == ["cloudflared", "zerotier"]


def test_deprio_empty_list_exits_0_no_output(stub_bridge):
    stub_bridge.responses[("GET", "/v1/agent/config")] = (
        200, {"ok": True, "deprioritized": []}
    )
    proc = _run_cli(["breaker", "deprio"], stub_bridge.url())
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_deprio_json_flag_emits_wrapper_object(stub_bridge):
    stub_bridge.responses[("GET", "/v1/agent/config")] = (
        200, {"ok": True, "deprioritized": ["cloudflared"]}
    )
    proc = _run_cli(["breaker", "deprio", "--json"], stub_bridge.url())
    assert proc.returncode == 3
    parsed = json.loads(proc.stdout)
    assert parsed == {"deprioritized": ["cloudflared"]}


def test_deprio_falls_back_to_breaker_summary_open_on_old_bridge(stub_bridge):
    """v4.15.x bridge doesn't ship the ``deprioritized`` key
    directly; CLI must fall back to ``breaker_summary.open``."""
    stub_bridge.responses[("GET", "/v1/agent/config")] = (
        200, {"ok": True,
              "breaker_summary": {"open": ["cloudflared"],
                                  "warn": [], "closed_ok": []}}
    )
    proc = _run_cli(["breaker", "deprio"], stub_bridge.url())
    assert proc.returncode == 3
    assert proc.stdout.strip() == "cloudflared"


# ---------------------------------------------------------------------------
# reset verb
# ---------------------------------------------------------------------------
def test_reset_all_posts_empty_body(stub_bridge):
    stub_bridge.responses[("POST", "/v1/tunnels/probe/reset")] = (
        200, {"ok": True, "reset": "all", "keys_cleared": 3}
    )
    proc = _run_cli(["breaker", "reset"], stub_bridge.url())
    assert proc.returncode == 0, proc.stderr
    assert "ok: reset=all cleared=3" in proc.stdout
    # Confirm the CLI POSTed an empty JSON body (not {"key": null}
    # or omitted -- server would treat those the same but we
    # promised an empty body).
    posts = [r for r in stub_bridge.received if r[0] == "POST"]
    assert len(posts) == 1
    body = json.loads(posts[0][2] or b"{}")
    assert body == {}


def test_reset_specific_key_posts_it(stub_bridge):
    stub_bridge.responses[("POST", "/v1/tunnels/probe/reset")] = (
        200, {"ok": True, "reset": "cloudflared|x:443",
              "keys_cleared": 1}
    )
    proc = _run_cli(["breaker", "reset", "cloudflared|x:443"],
                    stub_bridge.url())
    assert proc.returncode == 0
    assert "reset=cloudflared|x:443" in proc.stdout
    assert "cleared=1" in proc.stdout
    posts = [r for r in stub_bridge.received if r[0] == "POST"]
    body = json.loads(posts[0][2])
    assert body == {"key": "cloudflared|x:443"}


def test_reset_bridge_ok_false_exits_1(stub_bridge):
    stub_bridge.responses[("POST", "/v1/tunnels/probe/reset")] = (
        200, {"ok": False, "error": "internal"}
    )
    proc = _run_cli(["breaker", "reset"], stub_bridge.url())
    assert proc.returncode == 1
    assert "Reset failed" in proc.stderr


# ---------------------------------------------------------------------------
# Local summarize helper (v4.15.x compat path)
# ---------------------------------------------------------------------------
def test_local_summarize_mirrors_v416_helper():
    """CLI's ``_summarize`` (v4.15.x compat fallback) must produce
    identical output to the real
    ``arena.admin.tunnels_breaker.summarize_snapshot``. Regression
    guard against drift once someone updates one but not the
    other."""
    from arena.admin.tunnels_breaker import summarize_snapshot
    from arena.agentctl_cli.agentctl_breaker import _summarize
    snap = {
        "cloudflared|a:1": {"state": "open", "consecutive_failures": 3},
        "zerotier|b:2":    {"state": "closed", "consecutive_failures": 2},
        "tailscale|c:3":   {"state": "closed", "consecutive_failures": 0},
        "cloudflared|d:4": {"state": "closed", "consecutive_failures": 1},
    }
    assert _summarize(snap) == summarize_snapshot(snap)


def test_local_summarize_open_dominates_over_warn():
    from arena.agentctl_cli.agentctl_breaker import _summarize
    snap = {
        "cloudflared|a:1": {"state": "open", "consecutive_failures": 3},
        "cloudflared|b:2": {"state": "closed", "consecutive_failures": 1},
    }
    out = _summarize(snap)
    assert out["open"] == ["cloudflared"]
    assert out["warn"] == []
    assert out["open_count"] == 1
