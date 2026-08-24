"""Tests for the ``agentctl bridge`` CLI (v4.22.0).

Client-side URL discovery. Uses two stub HTTP servers so we can
prove ``bridge best`` really picks the fastest one (not just the
first advertised) — the bootstrap bridge advertises multiple URLs
via /v1/agent/config, and each candidate has its own /health
endpoint whose latency we control by injecting sleeps.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CLI = _REPO / "bin" / "agentctl"



def _bridge_module():
    """Import the CLI module lazily.

    Deliberately not a module-scope import: that would run
    `agentctl_common`'s import-time token/home-path evaluation for every
    test in this file, including the subprocess ones that do not need it.
    Raised in review of PR #176. The `sys.path` insert matches what 259
    other test modules in this suite already do -- changing that
    convention is not this PR's subject.
    """
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from arena.agentctl_cli import agentctl_bridge
    return agentctl_bridge


# ---------------------------------------------------------------------------
# Configurable stub. Each instance answers a fixed set of routes and
# can inject a per-route delay to simulate latency.
# ---------------------------------------------------------------------------
class _StubBridge:
    def __init__(self, responses: dict, delays: dict | None = None,
                 health_status: int = 200):
        self.responses = dict(responses)
        self.delays = dict(delays or {})
        self.health_status = health_status
        self.received: list[tuple[str, str]] = []
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
                path = self.path.split("?")[0]
                outer.received.append(("GET", path))
                if path in outer.delays:
                    time.sleep(outer.delays[path])
                if path == "/health":
                    self._write(outer.health_status, {"ok": True,
                                "service": "stub", "version": "test"})
                    return
                resp = outer.responses.get(("GET", path))
                if resp is None:
                    self._write(404, {"ok": False, "error": "not found"})
                    return
                status, body = resp
                self._write(status, body)

            def log_message(self, *_a, **_kw):
                pass

        # Bind once and never release: picking a port, closing the socket
        # and rebinding leaves a window in which the kernel may hand the
        # same port to another stub (#175).
        self.server = HTTPServer(("127.0.0.1", 0), _H)
        self.port = self.server.server_address[1]
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


def _run_cli(args: list[str], bridge_url: str):
    env = os.environ.copy()
    env.pop("ARENA_TOKEN_FILE", None)
    env["ARENA_BRIDGE_URL"] = bridge_url
    env["ARENA_BRIDGE_TOKEN"] = "stub-token"
    env["ARENA_AGENT_HOME"] = str(_REPO / "does-not-exist")
    return subprocess.run(
        [sys.executable, str(_CLI)] + args,
        capture_output=True, text=True, timeout=20, env=env,
    )


def _bootstrap(candidates: list[dict]) -> _StubBridge:
    """Start a stub bootstrap bridge that advertises ``candidates``
    from /v1/agent/config. Test is responsible for stopping it and
    for starting/stopping the candidate stubs themselves."""
    cfg = {
        "ok": True,
        "version": "test",
        "priority": [c["provider"] for c in candidates],
        "urls": candidates,
        "primary": {"provider": candidates[0]["provider"],
                    "public_url": candidates[0]["url"]} if candidates else None,
        "reachable_count": len(candidates),
        "deprioritized": [],
    }
    b = _StubBridge({("GET", "/v1/agent/config"): (200, cfg)})
    b.start()
    return b


# ---------------------------------------------------------------------------
# help / discovery
# ---------------------------------------------------------------------------
def test_help_lists_bridge_namespace():
    proc = _run_cli(["commands"], bridge_url="http://127.0.0.1:1")
    assert proc.returncode == 0
    assert "bridge" in proc.stdout
    assert "urls|best|test" in proc.stdout


def test_bridge_help_verb_prints_usage():
    proc = _run_cli(["bridge", "help"], bridge_url="http://127.0.0.1:1")
    assert proc.returncode == 0
    for kw in ("urls", "best", "test", "--json", "--timeout"):
        assert kw in proc.stdout, f"help missing keyword: {kw}"


# ---------------------------------------------------------------------------
# urls verb
# ---------------------------------------------------------------------------
def test_urls_lists_every_advertised_entry():
    boot = _bootstrap([
        {"provider": "tailscale", "url": "https://ts.example", "kind": "https"},
        {"provider": "zerotier",  "url": "http://10.0.0.1:8765",
         "kind": "http-lan"},
    ])
    try:
        proc = _run_cli(["bridge", "urls"], boot.url())
    finally:
        boot.stop()
    assert proc.returncode == 0, proc.stderr
    assert "tailscale" in proc.stdout
    assert "zerotier" in proc.stdout
    assert "https://ts.example" in proc.stdout


def test_urls_json_returns_raw_agent_config():
    boot = _bootstrap([
        {"provider": "tailscale", "url": "https://ts.example", "kind": "https"},
    ])
    try:
        proc = _run_cli(["bridge", "urls", "--json"], boot.url())
    finally:
        boot.stop()
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["urls"][0]["url"] == "https://ts.example"


def test_urls_bootstrap_unreachable_exits_1():
    """Nothing listening: bootstrap must exit 1, not crash."""
    proc = _run_cli(["bridge", "urls"], "http://127.0.0.1:1")
    assert proc.returncode == 1
    assert "agent/config" in proc.stderr


# ---------------------------------------------------------------------------
# best verb
# ---------------------------------------------------------------------------
def _measurement(url, provider, latency_ms):
    return {"url": url, "provider": provider, "kind": "https",
            "ok": True, "latency_ms": latency_ms, "status": 200, "error": None}


def _run_best_with(monkeypatch, measured, args=()):
    """Drive `best` against injected measurements and return its stdout."""
    agentctl_bridge = _bridge_module()
    monkeypatch.setattr(agentctl_bridge, "_fetch_config", lambda: {"urls": []})
    monkeypatch.setattr(agentctl_bridge, "_probe_all",
                        lambda cfg, timeout, m=measured: list(m))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        agentctl_bridge.best(list(args))
    return out.getvalue().strip()


def test_best_ranks_by_measured_latency_not_config_order(monkeypatch):
    """`best` must pick the lowest measured latency, not the first entry.

    #175: this used to be asserted by racing two live stubs, one delayed
    300ms and one 10ms, and checking which URL came back. That made a
    290ms wall-clock margin part of the contract. `_probe_all` probes
    sequentially, so any stall longer than the margin landing on the fast
    probe inverts the winner -- which is exactly how it failed on a macOS
    runner (`49582 != 49583`: two valid ports, the *slow* stub returned).
    Widening the margin would only make the flake rarer, and a failure
    that shows up once a quarter and is cleared by a re-run is worse than
    one that shows up every time.

    The ranking is pure given the measurements, so it is asserted against
    injected measurements. No clock, no sleep, no ports.
    """
    measured = [
        _measurement("https://slow.example", "slow-prov", 300.0),
        _measurement("https://fast.example", "fast-prov", 10.0),
    ]
    assert _run_best_with(monkeypatch, measured) == "https://fast.example"


def test_best_prefers_the_fastest_regardless_of_which_entry_is_listed_first(monkeypatch):
    """Config order must not decide the winner in either direction."""
    for fast_first in (True, False):
        measured = [
            _measurement("https://a.example", "a", 10.0 if fast_first else 300.0),
            _measurement("https://b.example", "b", 300.0 if fast_first else 10.0),
        ]
        expected = "https://a.example" if fast_first else "https://b.example"
        assert _run_best_with(monkeypatch, measured) == expected


def test_best_returns_the_only_reachable_url_end_to_end():
    """One live stub, no competing delays: the wiring still gets a real
    HTTP round trip, without any test depending on which of two probes
    wins a race."""
    fast = _StubBridge({}, delays={"/health": 0.01}).start()
    boot = _bootstrap([
        {"provider": "fast-prov", "url": fast.url(), "kind": "https"},
    ])
    try:
        proc = _run_cli(["bridge", "best"], boot.url())
    finally:
        boot.stop()
        fast.stop()
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == fast.url()


def test_best_json_reports_provider_and_latency():
    fast = _StubBridge({}, delays={"/health": 0.01}).start()
    boot = _bootstrap([
        {"provider": "fast-prov", "url": fast.url(), "kind": "https"},
    ])
    try:
        proc = _run_cli(["bridge", "best", "--json"], boot.url())
    finally:
        boot.stop()
        fast.stop()
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["provider"] == "fast-prov"
    assert payload["url"] == fast.url()
    assert isinstance(payload["latency_ms"], (int, float))
    assert payload["latency_ms"] >= 0


def test_best_exits_3_when_nothing_reachable():
    """All candidates point at unused ports → exit 3."""
    boot = _bootstrap([
        {"provider": "dead", "url": "http://127.0.0.1:1",  "kind": "https"},
        {"provider": "dead2","url": "http://127.0.0.1:2",  "kind": "https"},
    ])
    try:
        proc = _run_cli(["bridge", "best", "--timeout", "0.5"], boot.url())
    finally:
        boot.stop()
    assert proc.returncode == 3, (proc.returncode, proc.stdout, proc.stderr)


def test_best_skips_broken_url_and_returns_working_one():
    """One candidate is HTTP 500 on /health, one is healthy. The
    healthy one must win even if it's second in the priority
    order."""
    broken = _StubBridge({}, health_status=500).start()
    good = _StubBridge({}, delays={"/health": 0.01}).start()
    boot = _bootstrap([
        {"provider": "broken", "url": broken.url(), "kind": "https"},
        {"provider": "good",   "url": good.url(),   "kind": "https"},
    ])
    try:
        proc = _run_cli(["bridge", "best"], boot.url())
    finally:
        boot.stop()
        broken.stop()
        good.stop()
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == good.url()


# ---------------------------------------------------------------------------
# test verb
# ---------------------------------------------------------------------------
def test_test_verb_prints_table_for_every_candidate():
    good = _StubBridge({}, delays={"/health": 0.01}).start()
    boot = _bootstrap([
        {"provider": "good", "url": good.url(), "kind": "https"},
        {"provider": "dead", "url": "http://127.0.0.1:1", "kind": "https"},
    ])
    try:
        proc = _run_cli(["bridge", "test", "--timeout", "0.5"], boot.url())
    finally:
        boot.stop()
        good.stop()
    # Exit 0 because at least one candidate answered.
    assert proc.returncode == 0, proc.stderr
    assert "good" in proc.stdout
    assert "dead" in proc.stdout
    assert "yes" in proc.stdout
    assert "no" in proc.stdout


def test_test_verb_json_shape():
    good = _StubBridge({}, delays={"/health": 0.01}).start()
    boot = _bootstrap([
        {"provider": "good", "url": good.url(), "kind": "https"},
    ])
    try:
        proc = _run_cli(["bridge", "test", "--json"], boot.url())
    finally:
        boot.stop()
        good.stop()
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert len(payload["results"]) == 1
    r = payload["results"][0]
    assert r["provider"] == "good"
    assert r["ok"] is True
    assert r["url"] == good.url()


def test_test_exits_3_when_all_candidates_fail():
    boot = _bootstrap([
        {"provider": "dead", "url": "http://127.0.0.1:1", "kind": "https"},
    ])
    try:
        proc = _run_cli(["bridge", "test", "--timeout", "0.3"], boot.url())
    finally:
        boot.stop()
    assert proc.returncode == 3


# ---------------------------------------------------------------------------
# Regression: bad --timeout arg is a usage error, not a crash.
# ---------------------------------------------------------------------------
def test_bad_timeout_argument_exits_2():
    proc = _run_cli(["bridge", "best", "--timeout", "not-a-number"],
                    "http://127.0.0.1:1")
    assert proc.returncode == 2
    assert "--timeout" in proc.stderr
