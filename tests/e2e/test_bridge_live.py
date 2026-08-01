"""Live end-to-end tests: spawn the REAL bridge server process and talk to
it over real HTTP/TCP.

Doctrine reminder (see AGENTS.md): green unit tests prove the parts work in
isolation; they do NOT prove the shipped server actually starts, binds,
authenticates and serves the MCP protocol. These tests verify the observable
behaviour of a running process — the closest CI approximation to "a user just
started the bridge and pointed a client at it".

Two execution modes, selected by environment (same test code):

* source-tree mode (default, runs in the main test job): spawns
  ``sys.executable unified_bridge.py serve`` from the repo checkout.
* installed-artifact mode (the ``e2e-installed`` CI job): the job builds the
  wheel, installs it into a fresh venv and sets ``ARENA_E2E_SERVER_CMD`` to a
  JSON argv like ``["/path/to/venv/bin/python", "-m", "unified_bridge"]`` so
  the tests exercise the *shipped artifact*, not the source tree. Expected
  version stays the repo one, which cross-checks that the wheel's VERSION
  matches the tag being built.

No third-party HTTP client is used on purpose: stdlib http.client keeps the
artifact job free of the CI lock (the installed venv only has the bridge's
own runtime dependencies).
"""
from __future__ import annotations

import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_S = 40.0
REQUEST_TIMEOUT_S = 10.0


def _expected_version() -> str:
    override = os.environ.get("ARENA_E2E_EXPECT_VERSION")
    if override:
        return override
    sys.path.insert(0, str(REPO_ROOT))
    from arena.constants import VERSION  # noqa: PLC0415

    return VERSION


def _server_argv() -> list[str]:
    override = os.environ.get("ARENA_E2E_SERVER_CMD")
    if override:
        argv = json.loads(override)
        assert isinstance(argv, list) and all(isinstance(x, str) for x in argv)
        return argv
    return [sys.executable, str(REPO_ROOT / "unified_bridge.py")]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BridgeClient:
    """Minimal stdlib HTTP client with the bridge auth header baked in."""

    def __init__(self, port: int, token: str | None):
        self.port = port
        self.token = token

    def request(self, method: str, path: str, body: object = None,
                extra_headers: dict[str, str] | None = None,
                token: str | None = "__default__") -> tuple[int, dict, bytes,
                                                            dict[str, str]]:
        headers: dict[str, str] = {"Connection": "close"}
        eff = self.token if token == "__default__" else token
        if eff:
            headers["Authorization"] = f"Bearer {eff}"
        if extra_headers:
            headers.update(extra_headers)
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=REQUEST_TIMEOUT_S)
        try:
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {}
            return resp.status, parsed, raw, resp_headers
        finally:
            conn.close()

    def get(self, path: str, **kw):
        return self.request("GET", path, **kw)

    def post_json(self, path: str, payload: object, **kw):
        return self.request("POST", path, body=payload, **kw)


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    """One live server process per module (pytest-randomly safe)."""
    port = _free_port()
    # Prefix matters: token_urlsafe may emit a LEADING '-' (its alphabet
    # includes -_), and argparse then eats the value as an unknown option
    # ("argument --token: expected one argument") -> flaky rc=2 startups.
    token = "e2e-" + secrets.token_urlsafe(24)
    argv = _server_argv() + [
        "serve", "--bind", "127.0.0.1", "--port", str(port),
        "--token", token, "--root", str(REPO_ROOT),
    ]
    proc = subprocess.Popen(
        argv, cwd=str(tmp_path_factory.mktemp("bridge-cwd")),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    client = BridgeClient(port, token)
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            pytest.fail(f"bridge exited during startup rc={proc.returncode}:\n{out[-3000:]}")
        try:
            status, body, _, _ = client.get("/health")
            if status == 200 and body.get("ok"):
                break
        except (OSError, http.client.HTTPException) as e:
            last_err = e
        time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail(f"bridge did not become healthy in {STARTUP_TIMEOUT_S}s "
                    f"(last error: {last_err})")
    yield client
    proc.terminate()
    try:
        # aiohttp lets in-flight handlers finish; the SSE keepalive loop can
        # hold shutdown for up to its sleep cycle, so give SIGTERM real time
        # before escalating. On Windows terminate() is TerminateProcess —
        # no graceful-shutdown signal exists and the return code is the
        # forced exit status (observed 1), so only POSIX asserts signal
        # semantics; on Windows the contract is just "the process died".
        proc.wait(timeout=30)
        if os.name != "nt":
            assert proc.returncode in (0, -15, 15), \
                f"graceful shutdown expected, got rc={proc.returncode}"
        else:
            assert proc.returncode is not None
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        pytest.fail("bridge ignored SIGTERM for 30s and had to be SIGKILLed "
                    f"(rc={proc.returncode})")


# ---------------------------------------------------------------- bootstrap

def test_health_endpoint_is_public_and_reports_version(bridge):
    status, body, _, _ = bridge.get("/health", token=None)
    assert status == 200
    assert body["ok"] is True
    assert body["service"] == "arena-unified-bridge"
    assert body["version"] == _expected_version()
    assert body["uptime_seconds"] >= 0


def test_v1_version_reports_running_interpreter(bridge):
    status, body, _, _ = bridge.get("/v1/version")
    assert status == 200
    assert body["ok"] is True
    assert body["version"] == _expected_version()
    assert "python" in body and "platform" in body


# ------------------------------------------------------------------- auth

def test_mcp_requires_auth_missing_token(bridge):
    status, body, _, _ = bridge.post_json(
        "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        token=None)
    assert status == 401
    assert body.get("ok") is False or "error" in body


def test_mcp_requires_auth_wrong_token(bridge):
    status, body, _, _ = bridge.post_json(
        "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        token=secrets.token_urlsafe(24))
    assert status == 401


def test_v1_info_requires_auth(bridge):
    status, _, _, _ = bridge.get("/v1/info", token=None)
    assert status == 401


# -------------------------------------------------------------- MCP flow

def test_mcp_full_handshake_and_tool_surface(bridge):
    # initialize
    status, body, _, headers = bridge.post_json("/mcp", {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05",
                   "capabilities": {},
                   "clientInfo": {"name": "e2e", "version": "0"}},
    })
    assert status == 200
    assert body.get("jsonrpc") == "2.0" and body.get("id") == 1
    result = body.get("result") or {}
    assert result.get("serverInfo", {}).get("name"), \
        f"initialize result missing serverInfo: {body}"
    assert headers.get("mcp-session-id"), "missing Mcp-Session-Id header"

    # tools/list — the shipped tool surface must be non-empty and include
    # the canary exec.ping tool.
    status, body, _, _ = bridge.post_json(
        "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert status == 200
    tools = (body.get("result") or {}).get("tools") or []
    names = {t.get("name") for t in tools}
    assert len(names) > 100, f"tool surface implausibly small: {len(names)}"
    assert "exec.ping" in names

    # tools/call a pure read-only tool through the real executor path.
    status, body, _, _ = bridge.post_json("/mcp", {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "exec.ping", "arguments": {}}})
    assert status == 200
    result = body.get("result") or {}
    content = result.get("content") or []
    assert content and content[0].get("type") == "text"
    assert "pong" in content[0].get("text", "").lower()


# -------------------------------------------------- real work round-trip

def test_fs_write_read_roundtrip_through_tool_executor(bridge):
    """Real observable work, not a mock: the server process writes a file
    to disk and reads it back through the same MCP transport."""
    probe = Path.home() / f"arena-e2e-probe-{secrets.token_hex(4)}.txt"
    payload = f"arena-e2e-{secrets.token_hex(8)}"
    try:
        status, body, _, _ = bridge.post_json("/mcp", {
            "jsonrpc": "2.0", "id": 20, "method": "tools/call",
            "params": {"name": "fs.write",
                       "arguments": {"path": str(probe), "content": payload}}})
        assert status == 200
        result = body.get("result") or {}
        assert not result.get("isError"), body

        status, body, _, _ = bridge.post_json("/mcp", {
            "jsonrpc": "2.0", "id": 21, "method": "tools/call",
            "params": {"name": "fs.read",
                       "arguments": {"path": str(probe)}}})
        assert status == 200
        content = (body.get("result") or {}).get("content") or []
        assert content[0].get("text") == payload

        # Ground truth on the client side too (same machine, same user).
        assert probe.read_text(encoding="utf-8") == payload
    finally:
        probe.unlink(missing_ok=True)


def test_fs_jail_blocks_paths_outside_home(bridge):
    """Security fail-closed gate: the file jail must refuse paths outside
    the operator's home directory even when --root points elsewhere."""
    status, body, _, _ = bridge.post_json("/mcp", {
        "jsonrpc": "2.0", "id": 22, "method": "tools/call",
        "params": {"name": "fs.write",
                   "arguments": {"path": "/etc/arena-e2e-must-not-exist",
                                 "content": "x"}}})
    assert status == 200  # tool-level refusal lives in the result envelope
    result = body.get("result") or {}
    assert result.get("isError") is True
    assert "BLOCKED" in (result.get("content") or [{}])[0].get("text", "")
    assert not Path("/etc/arena-e2e-must-not-exist").exists()


# ------------------------------------------------------ negative / abuse

def test_malformed_json_gets_parse_error_and_server_survives(bridge):
    conn = http.client.HTTPConnection("127.0.0.1", bridge.port,
                                      timeout=REQUEST_TIMEOUT_S)
    try:
        conn.request("POST", "/mcp", body=b"{not json",
                     headers={"Content-Type": "application/json",
                              "Authorization": f"Bearer {bridge.token}"})
        resp = conn.getresponse()
        raw = resp.read()
        body = json.loads(raw)
        assert resp.status == 400
        assert body["error"]["code"] == -32700
    finally:
        conn.close()
    status, body, _, _ = bridge.get("/health", token=None)
    assert status == 200 and body["ok"] is True


def test_unknown_rpc_method_returns_jsonrpc_error(bridge):
    status, body, _, _ = bridge.post_json(
        "/mcp", {"jsonrpc": "2.0", "id": 9, "method": "no.such.method"})
    assert status in (200, 400)
    assert "error" in body or body.get("result") is None, body


def test_tool_call_unknown_tool_fails_closed(bridge):
    status, body, _, _ = bridge.post_json("/mcp", {
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "no.such.tool", "arguments": {}}})
    assert status == 200
    result = body.get("result") or {}
    # MCP convention: tool-level failure is result.isError=True, not HTTP 500.
    assert result.get("isError") is True or "error" in body, body


def test_unknown_route_is_404_not_crash(bridge):
    status, _, _, _ = bridge.get("/definitely-not-a-route")
    assert status == 404


def test_sse_stream_opens_with_endpoint_event(bridge):
    conn = http.client.HTTPConnection("127.0.0.1", bridge.port,
                                      timeout=REQUEST_TIMEOUT_S)
    try:
        conn.request("GET", "/sse",
                     headers={"Authorization": f"Bearer {bridge.token}"})
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Type", "").startswith("text/event-stream")
        chunk = resp.read1(512) if hasattr(resp, "read1") else resp.read(512)
        assert b"event: endpoint" in chunk
    finally:
        conn.close()
