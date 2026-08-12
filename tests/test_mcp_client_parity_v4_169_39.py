"""v4.169.39 -- arena.mcp_client.client parity tests (mutation-driven).

Fast, isolated tests for stdio MCP client and process lifecycle:
* `ALLOWED_COMMANDS` allowlist and `_command_allowed` path/extension resolution;
* `McpError` exception handling and exact refusal messages;
* `McpStdioClient` initialization, command security refusal, and environment tagging;
* `McpStdioClient.start`, `alive`, `stop` lifecycle, Popen kwargs, and initialization handshake;
* `McpStdioClient._start_reader` queue bounding (_MAX_LINE_CHARS and _STDOUT_QUEUE_DEPTH);
* `McpStdioClient._notify` and `request` JSON-RPC messaging, matching by id, timeout handling, broken pipes, and EOF;
* `McpStdioClient.list_tools` caching, refresh, and error handling;
* `McpStdioClient.call_tool` parameter passing, isError handling, structuredContent, and result envelope;
* `McpClientManager` config loading, client caching, pidfile recording, orphan reaping, status, stop, and stop_all.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.mcp_client.client as mcp_mod  # noqa: E402


class _FakePipe:
    def __init__(self):
        self._buf = io.StringIO()

    def write(self, s: str) -> int:
        return self._buf.write(s)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return self._buf.getvalue()


class _MockPopen:
    def __init__(self, stdout_lines: list[str] | None = None, pid: int = 12345):
        self.stdin = _FakePipe()
        self.stdout = io.StringIO("\n".join(stdout_lines) if stdout_lines else "")
        self.stderr = _FakePipe()
        self.pid = pid
        self._poll_val = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self._poll_val

    def terminate(self) -> None:
        self.terminated = True
        self._poll_val = -15

    def wait(self, timeout: float | None = None) -> int:
        return self._poll_val or 0

    def kill(self) -> None:
        self.killed = True
        self._poll_val = -9


# --------------------------------------------------------------------
# 0. Command Allowlist & Security
# --------------------------------------------------------------------
def test_allowed_commands_pinned():
    assert mcp_mod.ALLOWED_COMMANDS == ("npx", "uvx", "uv", "python", "python3", "node")
    assert mcp_mod._MAX_LINE_CHARS == 4 * 1024 * 1024
    assert mcp_mod._STDOUT_QUEUE_DEPTH == 1000
    assert mcp_mod._PROTOCOL_VERSION == "2025-03-26"
    assert mcp_mod._CLIENT_INFO == {"name": "arena-bridge", "version": "1.0"}


@pytest.mark.parametrize(
    "cmd,expected",
    [
        ("npx", True),
        ("uvx", True),
        ("uv", True),
        ("python", True),
        ("python3", True),
        ("node", True),
        (r"C:\venv\Scripts\python.exe", True),
        (r"C:\bin\node.cmd", True),
        (r"C:\bin\uvx.bat", True),
        ("/usr/local/bin/python3.11", True),
        ("/usr/bin/python312", True),
        # Disallowed
        ("sh", False),
        ("bash", False),
        ("cmd", False),
        ("powershell", False),
        ("pwsh", False),
        ("/bin/curl", False),
        ("arbitrary_binary", False),
    ],
)
def test_command_allowed_resolution(cmd, expected):
    assert mcp_mod._command_allowed(cmd) == expected


def test_client_init_disallowed_command_raises():
    with pytest.raises(mcp_mod.McpError) as exc:
        mcp_mod.McpStdioClient("bash", ["script.sh"])
    assert str(exc.value) == (
        "refusing to spawn unknown command 'bash' (allowed: npx, uvx, uv, python, python3, node or a full path to one)"
    )


def test_client_init_tags_environment(monkeypatch):
    client = mcp_mod.McpStdioClient("python", ["-m", "server"], env={"CUSTOM_VAR": "val"}, cwd="/tmp/mcp_work")
    assert client.command == "python"
    assert client.args == ["-m", "server"]
    assert client.cwd == "/tmp/mcp_work"
    assert client.env["ARENA_MCP_CHILD"] == "1"
    assert client.env["CUSTOM_VAR"] == "val"
    assert client.proc is None
    assert client._tools is None
    assert client.server_info == {}
    assert client._stdout_q.maxsize == 1000


# --------------------------------------------------------------------
# 1. McpStdioClient Lifecycle & Handshake
# --------------------------------------------------------------------
def test_client_start_not_found(monkeypatch):
    def _fail_popen(*a, **k):
        raise FileNotFoundError("no python")

    monkeypatch.setattr(mcp_mod.subprocess, "Popen", _fail_popen)
    client = mcp_mod.McpStdioClient("python", [])

    with pytest.raises(mcp_mod.McpError) as exc:
        client.start()
    assert str(exc.value) == "command not found: python (install it / check npx|uvx|python is on PATH)"


def test_client_start_happy_path(monkeypatch):
    init_resp = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"protocolVersion": "2025-03-26", "serverInfo": {"name": "test-server", "version": "0.1"}},
    }
    mock_proc = _MockPopen()
    captured_popen = {}

    def _fake_popen(args, **kwargs):
        captured_popen["args"] = args
        captured_popen["kwargs"] = kwargs
        return mock_proc

    monkeypatch.setattr(mcp_mod.subprocess, "Popen", _fake_popen)
    client = mcp_mod.McpStdioClient("node", ["server.js"], cwd="/app")

    # Push matching response into queue
    client._stdout_q.put_nowait(json.dumps(init_resp) + "\n")

    info = client.start(timeout=10)
    assert info == init_resp["result"]
    assert client.server_info == init_resp["result"]
    assert client.alive() is True

    # Check Popen kwargs
    assert captured_popen["args"] == ["node", "server.js"]
    assert captured_popen["kwargs"]["text"] is True
    assert captured_popen["kwargs"]["bufsize"] == 1
    assert captured_popen["kwargs"]["cwd"] == "/app"

    # Check handshake written to stdin
    written = mock_proc.stdin.getvalue().splitlines()
    assert len(written) == 2
    init_req = json.loads(written[0])
    assert init_req == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "arena-bridge", "version": "1.0"},
        },
    }
    notif = json.loads(written[1])
    assert notif == {"jsonrpc": "2.0", "method": "notifications/initialized"}

    # Second start is idempotent and returns cached server_info
    assert client.start(timeout=10) == init_resp["result"]


def test_client_stop_and_kill_fallback():
    mock_proc = _MockPopen()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc
    client._tools = [{"name": "tool1"}]

    assert client.alive() is True
    client.stop()
    assert client.alive() is False
    assert client.proc is None
    assert client._tools is None
    assert mock_proc.terminated is True


def test_client_stop_kill_when_terminate_raises():
    class _FailingTerminateProc(_MockPopen):
        def terminate(self):
            raise OSError("cannot terminate")

    mock_proc = _FailingTerminateProc()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc

    client.stop()
    assert mock_proc.killed is True
    assert client.proc is None


# --------------------------------------------------------------------
# 2. McpStdioClient Request / Response / Broken Pipe
# --------------------------------------------------------------------
def test_client_request_not_running():
    client = mcp_mod.McpStdioClient("python", [])
    with pytest.raises(mcp_mod.McpError) as exc:
        client.request("test_method")
    assert str(exc.value) == "server is not running"


def test_client_notify_not_running():
    client = mcp_mod.McpStdioClient("python", [])
    with pytest.raises(mcp_mod.McpError) as exc:
        client._notify("test_notify")
    assert str(exc.value) == "server is not running"


def test_client_notify_running():
    mock_proc = _MockPopen()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc

    client._notify("custom/event", {"key": "val"})
    written = mock_proc.stdin.getvalue()
    assert json.loads(written) == {"jsonrpc": "2.0", "method": "custom/event", "params": {"key": "val"}}


def test_client_request_broken_pipe():
    class _BrokenPipe:
        def write(self, s):
            raise BrokenPipeError("pipe closed")

    mock_proc = _MockPopen()
    mock_proc.stdin = _BrokenPipe()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc

    with pytest.raises(mcp_mod.McpError) as exc:
        client.request("broken_method")
    assert "server pipe broken: pipe closed" in str(exc.value)


def test_client_request_timeout(monkeypatch):
    mock_proc = _MockPopen()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc

    # Empty queue causes timeout
    with pytest.raises(mcp_mod.McpError) as exc:
        client.request("slow_method", timeout=0.05)
    assert "timed out after 0.05s; server stopped" in str(exc.value)
    assert mock_proc.terminated is True


def test_client_request_eof_server_crashed(monkeypatch):
    mock_proc = _MockPopen()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc

    # Put None (EOF marker)
    client._stdout_q.put_nowait(None)

    with pytest.raises(mcp_mod.McpError) as exc:
        client.request("method_crashes", timeout=5)
    assert str(exc.value) == "server closed the connection (it likely crashed)"


def test_client_request_skips_notifications_and_stale_ids():
    mock_proc = _MockPopen()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc

    # Push non-json, notifications, stale ids, and finally matching id=1
    client._stdout_q.put_nowait("non json line\n")
    client._stdout_q.put_nowait(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress"}) + "\n")
    client._stdout_q.put_nowait(json.dumps({"jsonrpc": "2.0", "id": 999, "result": "stale"}) + "\n")
    client._stdout_q.put_nowait(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}) + "\n")

    res = client.request("my_call", params={"param1": "val1"}, timeout=5)
    assert res == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    written = mock_proc.stdin.getvalue()
    assert '"params": {"param1": "val1"}' in written


# --------------------------------------------------------------------
# 3. McpStdioClient Tool Conveniences
# --------------------------------------------------------------------
def test_client_list_tools_caching_and_refresh():
    mock_proc = _MockPopen()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc

    # First call queries tools/list
    client._stdout_q.put_nowait(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "t1"}]}}) + "\n")
    tools1 = client.list_tools(timeout=5)
    assert tools1 == [{"name": "t1"}]

    # Second call returns cached without querying
    tools2 = client.list_tools(timeout=5, refresh=False)
    assert tools2 == [{"name": "t1"}]

    # Refresh queries again
    client._stdout_q.put_nowait(json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "t2"}]}}) + "\n")
    tools3 = client.list_tools(timeout=5, refresh=True)
    assert tools3 == [{"name": "t2"}]


def test_client_list_tools_error_raises():
    mock_proc = _MockPopen()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc

    client._stdout_q.put_nowait(json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}) + "\n")
    with pytest.raises(mcp_mod.McpError) as exc:
        client.list_tools(timeout=5)
    assert str(exc.value) == "tools/list error: {'code': -32601, 'message': 'Method not found'}"


def test_client_call_tool_success_and_error():
    mock_proc = _MockPopen()
    client = mcp_mod.McpStdioClient("python", [])
    client.proc = mock_proc

    # 1. Success tool call
    client._stdout_q.put_nowait(json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": "result content"}],
            "structuredContent": {"k": "v"},
            "isError": False,
        },
    }) + "\n")
    res1 = client.call_tool("my_tool", {"arg": "val"}, timeout=5)
    assert res1 == {
        "ok": True,
        "content": [{"type": "text", "text": "result content"}],
        "structured": {"k": "v"},
        "isError": False,
    }

    # 2. Tool returns isError=True
    client._stdout_q.put_nowait(json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"content": [{"type": "text", "text": "syntax error"}], "isError": True},
    }) + "\n")
    res2 = client.call_tool("tool_with_is_error", timeout=5)
    assert res2 == {
        "ok": False,
        "content": [{"type": "text", "text": "syntax error"}],
        "structured": None,
        "isError": True,
    }

    # 3. JSON-RPC error response
    client._stdout_q.put_nowait(json.dumps({
        "jsonrpc": "2.0",
        "id": 3,
        "error": {"code": -32000, "message": "tool execution failed"},
    }) + "\n")
    res3 = client.call_tool("failing_tool", timeout=5)
    assert res3 == {"ok": False, "error": {"code": -32000, "message": "tool execution failed"}}


# --------------------------------------------------------------------
# 4. McpClientManager & Orphan Reaping
# --------------------------------------------------------------------
def test_manager_safe_name_and_pidfile(tmp_path):
    conf = tmp_path / "mcp.json"
    mgr = mcp_mod.McpClientManager(config_path=conf)

    assert mgr._safe_name("my-server.v1:prod") == "my-server.v1_prod"
    pidf = mgr._pidfile("my-server.v1:prod")
    assert pidf.name == "my-server.v1_prod.json"
    assert pidf.parent == tmp_path / "run"


def test_manager_load_config_and_servers(tmp_path):
    conf = tmp_path / "mcp.json"
    conf.write_text(json.dumps({
        "mcpServers": {
            "test_server": {
                "command": "python",
                "args": ["-m", "server"],
                "env": {"FOO": "BAR"},
            }
        }
    }), encoding="utf-8")

    mgr = mcp_mod.McpClientManager(config_path=conf)
    servers = mgr.servers()
    assert "test_server" in servers
    assert servers["test_server"]["command"] == "python"


def test_manager_load_config_corrupt_or_missing(tmp_path):
    conf_missing = tmp_path / "missing_mcp.json"
    mgr1 = mcp_mod.McpClientManager(config_path=conf_missing)
    assert mgr1.servers() == {}

    conf_corrupt = tmp_path / "bad_mcp.json"
    conf_corrupt.write_text("not-json", encoding="utf-8")
    mgr2 = mcp_mod.McpClientManager(config_path=conf_corrupt)
    assert mgr2.servers() == {}


def test_manager_get_client_unregistered_raises(tmp_path):
    conf = tmp_path / "mcp.json"
    conf.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

    mgr = mcp_mod.McpClientManager(config_path=conf)
    with pytest.raises(mcp_mod.McpError) as exc:
        mgr.get_client("nonexistent")
    assert "is not registered in" in str(exc.value)


def test_manager_lifecycle(tmp_path, monkeypatch):
    conf = tmp_path / "mcp.json"
    conf.write_text(json.dumps({
        "mcpServers": {
            "srv1": {"command": "python", "args": ["s1.py"]},
            "srv2": {"command": "node", "args": ["s2.js"]},
        }
    }), encoding="utf-8")

    init_line = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n"
    tools_line = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "tool_x"}]}}) + "\n"
    call_line = json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"content": [{"text": "out"}]}}) + "\n"

    proc1 = _MockPopen(stdout_lines=[init_line, tools_line, call_line], pid=1001)
    proc2 = _MockPopen(stdout_lines=[init_line], pid=1002)
    procs = [proc1, proc2]

    monkeypatch.setattr(mcp_mod.subprocess, "Popen", lambda *a, **k: procs.pop(0))

    mgr = mcp_mod.McpClientManager(config_path=conf)

    mgr.get_client("srv1")
    assert mgr.status("srv1") == {"registered": True, "running": True}
    assert mgr.status("srv2") == {"registered": True, "running": False}

    # list_tools and call_tool via manager facade
    assert mgr.list_tools("srv1") == [{"name": "tool_x"}]
    assert mgr.call_tool("srv1", "tool_x")["ok"] is True

    # Stop single
    mgr.stop("srv1")
    assert mgr.status("srv1") == {"registered": True, "running": False}

    # Stop all
    mgr.stop_all()


def test_manager_reap_orphans(tmp_path, monkeypatch):
    conf = tmp_path / "mcp.json"
    conf.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

    mgr = mcp_mod.McpClientManager(config_path=conf)
    run_dir = mgr._run_dir()

    # 1. Corrupt pidfile -> unlinked
    (run_dir / "corrupt.json").write_text("bad json", encoding="utf-8")

    # 2. Non-int child_pid -> unlinked
    (run_dir / "bad_pid.json").write_text(json.dumps({"pid": "not_an_int"}), encoding="utf-8")

    # 3. Dead bridge process orphan (bridge_pid=99999) -> reaped
    pidfile = run_dir / "orphan_srv.json"
    pidfile.write_text(json.dumps({
        "name": "orphan_srv",
        "pid": 88888,
        "bridge_pid": 99999,
        "started": 100.0,
        "command": "python",
    }), encoding="utf-8")

    class _MockProcess:
        def __init__(self, pid):
            self.pid = pid
            self.terminated = False

        def create_time(self):
            return 100.0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    mock_proc = _MockProcess(88888)
    mock_psutil = MagicMock()
    mock_psutil.Process.return_value = mock_proc
    mock_psutil.pid_exists.side_effect = lambda pid: pid != 99999  # bridge_pid 99999 is dead

    monkeypatch.setattr("psutil.Process", mock_psutil.Process)
    monkeypatch.setattr("psutil.pid_exists", mock_psutil.pid_exists)

    res = mgr.reap_orphans()
    assert res == {"ok": True, "reaped": [88888], "skipped": []}
    assert mock_proc.terminated is True
    assert not pidfile.exists()


def test_get_manager_singleton_and_atexit():
    m1 = mcp_mod.get_manager()
    m2 = mcp_mod.get_manager()
    assert m1 is m2

    # Verify _atexit_stop_all executes safely
    mcp_mod._atexit_stop_all()
