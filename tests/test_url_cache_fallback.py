"""End-to-end tests for the v4.39.0 cache-fallback loop.

Uses subprocess + stub HTTP servers (same pattern as
``tests/test_agentctl_bridge.py``) so we exercise the whole
path from CLI argv through _fetch_config's fallback loop.

Two failure modes exercised:
  * bootstrap URL returns HTTP 5xx / times out -> cache
    fallback picks up a healthy alternative
  * bootstrap AND cache both empty -> exit 1 as before
    (no silent success)

Plus the ``cache show`` / ``cache clear`` verbs verified.
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
# Stub bridge (adapted from tests/test_agentctl_bridge.py). Each instance
# serves a fixed /v1/agent/config response.
# ---------------------------------------------------------------------------
class _StubBridge:
    """Toy HTTP server pretending to be a bridge. Responses can
    be swapped mid-test by mutating ``self.responses``, and we
    can inject 5xx to simulate outage without shutting the
    server down (which would give the client a totally different
    error class -- connection-refused vs HTTP 503)."""

    def __init__(self, agent_config: dict | None,
                 health_status: int = 200):
        self.agent_config = agent_config
        self.health_status = health_status
        self.received: list[tuple[str, str]] = []
        self.server = None
        self.thread = None
        self.port = 0
        # When set to a non-200 value, /v1/agent/config returns
        # that status. Simulates "bridge alive but sick".
        self.config_status = 200

    def start(self):
        outer = self

        class _H(BaseHTTPRequestHandler):
            def _write(self, status, body):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                data = (body if isinstance(body, bytes)
                        else json.dumps(body).encode())
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split("?")[0]
                outer.received.append(("GET", path))
                if path == "/health":
                    self._write(outer.health_status,
                                {"ok": True, "service": "stub"})
                    return
                if path == "/v1/agent/config":
                    if outer.config_status != 200:
                        self._write(outer.config_status,
                                    {"ok": False, "error": "sick"})
                        return
                    self._write(200, outer.agent_config or {})
                    return
                self._write(404, {"ok": False, "error": "not found"})

            def log_message(self, *_a, **_kw):
                pass

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


def _agent_config_for(*bridges) -> dict:
    """Build a valid /v1/agent/config payload advertising the
    given stub bridges as urls."""
    urls = [
        {"provider": f"stub-{i}", "url": b.url(), "kind": "http"}
        for i, b in enumerate(bridges)
    ]
    return {
        "ok": True,
        "version": "test",
        "priority": [u["provider"] for u in urls],
        "urls": urls,
        "primary": (
            {"provider": urls[0]["provider"], "public_url": urls[0]["url"]}
            if urls else None
        ),
        "reachable_count": len(urls),
        "deprioritized": [],
    }


def _run_cli(args, bootstrap_url, cache_path=None, extra_env=None,
             timeout=20):
    """Spawn the agentctl CLI with a per-test cache path and
    bootstrap URL. Returns CompletedProcess."""
    env = os.environ.copy()
    env.pop("ARENA_TOKEN_FILE", None)
    env["ARENA_BRIDGE_URL"] = bootstrap_url
    env["ARENA_BRIDGE_TOKEN"] = "stub-token"
    env["ARENA_AGENT_HOME"] = str(_REPO / "does-not-exist")
    if cache_path is not None:
        env["ARENA_URL_CACHE_PATH"] = str(cache_path)
    env.pop("ARENA_BRIDGE_URL_CACHE", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(_CLI), "bridge"] + args,
        capture_output=True, text=True, timeout=timeout, env=env,
    )


# ---------------------------------------------------------------------------
# Fresh save -- happy path warms the cache
# ---------------------------------------------------------------------------
def test_successful_bootstrap_writes_cache(tmp_path):
    """Every successful /v1/agent/config call must persist the
    URL list so a future outage has something to fall back on."""
    good = _StubBridge(None).start()
    good.agent_config = _agent_config_for(good)
    cache = tmp_path / "cache.json"
    try:
        proc = _run_cli(["urls"], good.url(), cache_path=cache)
    finally:
        good.stop()
    assert proc.returncode == 0, proc.stderr
    assert cache.exists()
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert saved["bootstrap_url"] == good.url()
    assert len(saved["urls"]) == 1
    assert saved["urls"][0]["url"] == good.url()


# ---------------------------------------------------------------------------
# Fallback -- bootstrap unreachable, cached URL still works
# ---------------------------------------------------------------------------
def test_bootstrap_dead_but_cache_saves_the_day(tmp_path):
    """The exact scenario Ivan hit: primary URL is unreachable
    but the cache holds another URL that still works."""
    # Two live bridges, we'll pretend the first one died.
    dead = _StubBridge(None).start()
    alive = _StubBridge(None).start()
    alive.agent_config = _agent_config_for(alive)

    cache = tmp_path / "cache.json"

    # Prime the cache with both URLs (as if a previous run had
    # seen both healthy).
    cache.write_text(json.dumps({
        "version": 1,
        "saved_at": int(time.time()),
        "bootstrap_url": dead.url(),
        "urls": [
            {"provider": "dead-primary", "url": dead.url(), "kind": "http"},
            {"provider": "alive-fallback", "url": alive.url(), "kind": "http"},
        ],
    }), encoding="utf-8")

    # Now shut the "primary" down so the CLI's first attempt fails.
    dead_url = dead.url()
    dead.stop()

    try:
        proc = _run_cli(["urls"], dead_url, cache_path=cache, timeout=25)
    finally:
        alive.stop()

    # Fallback should have succeeded via alive; exit 0.
    assert proc.returncode == 0, (
        f"expected fallback success; stderr:\n{proc.stderr}\n"
        f"stdout:\n{proc.stdout}"
    )
    # Diagnostic on stderr tells operator what saved them.
    assert "cached URL" in proc.stderr
    assert alive.url() in proc.stderr
    # stdout has the healthy bridge's URL list.
    assert alive.url() in proc.stdout


def test_fallback_refreshes_cache_from_new_response(tmp_path):
    """When a fallback URL serves, the cache is refreshed with
    the new snapshot -- picks up rotated URLs automatically."""
    dead = _StubBridge(None).start()
    alive = _StubBridge(None).start()
    # ALIVE now advertises a NEW third URL that wasn't in the
    # original cache -- simulates a rotated cloudflared domain.
    new_url_bridge = _StubBridge(None).start()
    new_url_bridge.agent_config = _agent_config_for(new_url_bridge)
    alive.agent_config = _agent_config_for(alive, new_url_bridge)

    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "version": 1,
        "saved_at": int(time.time()),
        "bootstrap_url": dead.url(),
        "urls": [
            {"provider": "dead", "url": dead.url(), "kind": "http"},
            {"provider": "alive", "url": alive.url(), "kind": "http"},
        ],
    }), encoding="utf-8")

    dead_url = dead.url()
    dead.stop()

    try:
        proc = _run_cli(["urls"], dead_url, cache_path=cache, timeout=25)
    finally:
        alive.stop()
        new_url_bridge.stop()

    assert proc.returncode == 0, proc.stderr

    # Cache should have been refreshed with the freshly-seen
    # third URL.
    refreshed = json.loads(cache.read_text(encoding="utf-8"))
    urls_now = [u["url"] for u in refreshed["urls"]]
    assert new_url_bridge.url() in urls_now, (
        f"cache did not pick up rotated URL: {urls_now}"
    )
    assert refreshed["bootstrap_url"] == alive.url()


def test_all_urls_dead_exits_1(tmp_path):
    """When both the bootstrap AND every cached URL are dead,
    fall back to the pre-v4.39.0 behaviour: print error, exit 1."""
    dead1 = _StubBridge(None).start()
    dead2 = _StubBridge(None).start()

    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "version": 1,
        "saved_at": int(time.time()),
        "bootstrap_url": dead1.url(),
        "urls": [
            {"provider": "d1", "url": dead1.url(), "kind": "http"},
            {"provider": "d2", "url": dead2.url(), "kind": "http"},
        ],
    }), encoding="utf-8")

    d1, d2 = dead1.url(), dead2.url()
    dead1.stop()
    dead2.stop()

    proc = _run_cli(["urls"], d1, cache_path=cache, timeout=25)
    assert proc.returncode == 1
    # Original error on stderr.
    assert "could not reach" in proc.stderr
    # The "also tried N cached URL(s)" hint should mention the count.
    assert "also tried" in proc.stderr


def test_cache_disabled_env_skips_fallback(tmp_path):
    """When ARENA_BRIDGE_URL_CACHE=0, an outage exits 1
    immediately -- no cache read attempted. Verified by ensuring
    the cache file present on disk is ignored."""
    dead = _StubBridge(None).start()
    alive = _StubBridge(None).start()
    alive.agent_config = _agent_config_for(alive)

    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "version": 1,
        "saved_at": int(time.time()),
        "bootstrap_url": dead.url(),
        "urls": [
            {"provider": "alive", "url": alive.url(), "kind": "http"},
        ],
    }), encoding="utf-8")

    dead_url = dead.url()
    dead.stop()

    try:
        proc = _run_cli(
            ["urls"], dead_url,
            cache_path=cache,
            extra_env={"ARENA_BRIDGE_URL_CACHE": "0"},
            timeout=15,
        )
    finally:
        alive.stop()

    # Cache was disabled, so fallback did NOT run. Exit 1.
    assert proc.returncode == 1
    # Should NOT have the "cached URL" success hint.
    assert "cached URL" not in proc.stderr


def test_cache_skips_bootstrap_url_dedup(tmp_path):
    """When the bootstrap URL is also present in the cache
    (very common -- ARENA_BRIDGE_URL usually IS the first
    URL the server hands back), fallback must not waste a
    second timeout trying the same failing URL."""
    dead = _StubBridge(None).start()
    alive = _StubBridge(None).start()
    alive.agent_config = _agent_config_for(alive)

    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "version": 1,
        "saved_at": int(time.time()),
        "bootstrap_url": dead.url(),
        "urls": [
            # bootstrap URL first -- same as ARENA_BRIDGE_URL
            {"provider": "dead", "url": dead.url(), "kind": "http"},
            {"provider": "alive", "url": alive.url(), "kind": "http"},
        ],
    }), encoding="utf-8")

    dead_url = dead.url()
    dead.stop()

    try:
        proc = _run_cli(["urls"], dead_url, cache_path=cache, timeout=15)
    finally:
        alive.stop()

    assert proc.returncode == 0, proc.stderr
    # alive.url() should be the one that served.
    assert alive.url() in proc.stderr


# ---------------------------------------------------------------------------
# `bridge cache` verb
# ---------------------------------------------------------------------------
def test_cache_show_empty_reports_no_cache(tmp_path):
    """Empty cache is a valid state (fresh install). Must exit
    0 and print an informative message, not error out."""
    proc = _run_cli(["cache", "show"],
                    bootstrap_url="http://127.0.0.1:1",
                    cache_path=tmp_path / "cache.json")
    assert proc.returncode == 0
    assert "no cache" in proc.stdout
    assert "path:" in proc.stdout


def test_cache_show_populated_prints_table(tmp_path):
    good = _StubBridge(None).start()
    good.agent_config = _agent_config_for(good)
    cache = tmp_path / "cache.json"
    try:
        # Prime the cache via a real bridge call.
        prime = _run_cli(["urls"], good.url(), cache_path=cache)
        assert prime.returncode == 0
        # Now show it.
        proc = _run_cli(["cache", "show"], good.url(), cache_path=cache)
    finally:
        good.stop()
    assert proc.returncode == 0
    assert "saved_at:" in proc.stdout
    assert good.url() in proc.stdout


def test_cache_show_json_returns_structured_output(tmp_path):
    good = _StubBridge(None).start()
    good.agent_config = _agent_config_for(good)
    cache = tmp_path / "cache.json"
    try:
        _run_cli(["urls"], good.url(), cache_path=cache)
        proc = _run_cli(["cache", "show", "--json"], good.url(),
                        cache_path=cache)
    finally:
        good.stop()
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["disabled"] is False
    assert payload["cache"] is not None
    assert good.url() in [u["url"] for u in payload["cache"]["urls"]]


def test_cache_clear_removes_file(tmp_path):
    good = _StubBridge(None).start()
    good.agent_config = _agent_config_for(good)
    cache = tmp_path / "cache.json"
    try:
        _run_cli(["urls"], good.url(), cache_path=cache)
        assert cache.exists()
        proc = _run_cli(["cache", "clear"], good.url(), cache_path=cache)
    finally:
        good.stop()
    assert proc.returncode == 0
    assert "removed" in proc.stdout
    assert not cache.exists()


def test_cache_clear_no_file_reports_gracefully(tmp_path):
    proc = _run_cli(["cache", "clear"],
                    bootstrap_url="http://127.0.0.1:1",
                    cache_path=tmp_path / "cache.json")
    assert proc.returncode == 0
    assert "no cache" in proc.stdout.lower()


def test_cache_unknown_subverb_exits_2(tmp_path):
    proc = _run_cli(["cache", "bogus"],
                    bootstrap_url="http://127.0.0.1:1",
                    cache_path=tmp_path / "cache.json")
    assert proc.returncode == 2
    assert "unknown cache sub-verb" in proc.stderr


def test_help_mentions_cache_verb():
    """Discoverability check: `bridge help` should mention the
    new verb so users find it without reading the source."""
    env = os.environ.copy()
    env.pop("ARENA_TOKEN_FILE", None)
    env["ARENA_BRIDGE_URL"] = "http://127.0.0.1:1"
    env["ARENA_BRIDGE_TOKEN"] = "stub-token"
    env["ARENA_AGENT_HOME"] = str(_REPO / "does-not-exist")
    proc = subprocess.run(
        [sys.executable, str(_CLI), "bridge", "help"],
        capture_output=True, text=True, timeout=10, env=env,
    )
    assert proc.returncode == 0
    assert "cache" in proc.stdout
    assert "persistent URL memory" in proc.stdout
    assert "ARENA_BRIDGE_URL_CACHE" in proc.stdout
