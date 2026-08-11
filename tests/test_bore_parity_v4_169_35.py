"""v4.169.35 -- bore tunnel parity tests (mutation-driven).

Baseline measured with mutmut 2.5.1: 141/309 mutants of
``arena/admin/bore.py`` survived. Cause: existing tests did not assert
exact return dictionary schemas, error classifier hint texts, candidate
resolution paths per OS, boundary conditions for port/wait clamps, or
subprocess argv/kwargs contracts.

This test module pins every observable behaviour:
* test-side independent copies of all candidate paths, hint strings,
  and error classifier messages;
* full boundary coverage for environment variable parsers;
* mock/spy isolation for Popen, monitor thread, poll loops, timeouts,
  and termination routines;
* exact dictionary key/value assertions across all branches of `bore_action`.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.admin.bore as bore_mod  # noqa: E402

# ---------------------------------------------------------------------------
# Test-side copies of contracts and constants
# ---------------------------------------------------------------------------
EXPECTED_URL_WAIT_MIN = 1.0
EXPECTED_URL_WAIT_MAX = 300.0
EXPECTED_URL_WAIT_DEFAULT = 30.0
EXPECTED_URL_WAIT_POLL_INTERVAL = 0.5
EXPECTED_ENV_URL_WAIT = "ARENA_BORE_URL_WAIT_SECONDS"
EXPECTED_DEFAULT_SERVER = "bore.pub"
EXPECTED_DEFAULT_LOCAL_HOST = "localhost"

EXPECTED_WINDOWS_CANDIDATES = [
    r"C:\Program Files\bore\bore.exe",
    r"C:\Program Files (x86)\bore\bore.exe",
]
EXPECTED_DARWIN_CANDIDATES = [
    "/usr/local/bin/bore",
    "/opt/homebrew/bin/bore",
]
EXPECTED_POSIX_CANDIDATES = [
    "/usr/local/bin/bore",
    str(Path.home() / ".cargo/bin/bore"),
    "/snap/bin/bore",
]

EXPECTED_SYSTEM_UPDATE_HINT = (
    "Update via `cargo install bore-cli` -- or download the "
    "latest release binary from https://github.com/ekzhang/bore/releases"
)
EXPECTED_BUNDLED_UPDATE_HINT = (
    "Bundled binary managed by Arena. Run: "
    "`python3 scripts/update_bundled_tools.py bore`"
)
EXPECTED_NOT_FOUND_HINT_WINDOWS = (
    "Install bore: download the Windows release binary from "
    "https://github.com/ekzhang/bore/releases and place it in "
    "PATH, or install Rust and run `cargo install bore-cli`."
)
EXPECTED_NOT_FOUND_HINT_DARWIN = (
    "Install bore: `cargo install bore-cli` (requires Rust), "
    "or download from https://github.com/ekzhang/bore/releases"
)
EXPECTED_NOT_FOUND_HINT_POSIX = (
    "Install bore: `cargo install bore-cli` (requires Rust), or "
    "download the release binary from "
    "https://github.com/ekzhang/bore/releases"
)

EXPECTED_HINT_INVALID_SECRET = (
    "The ARENA_BORE_SECRET value does not match the bore server's "
    "``--secret``. Re-copy the shared secret or unset "
    "ARENA_BORE_SECRET when connecting to bore.pub."
)
EXPECTED_HINT_SERVER_UNREACHABLE = (
    "Cannot reach the bore server. Check network connectivity or "
    "point ARENA_BORE_SERVER at a reachable host."
)
EXPECTED_HINT_PORT_CONFLICT = (
    "The requested remote port is already in use on the bore server. "
    "Unset ARENA_BORE_REMOTE_PORT so the server picks a free port, "
    "or pick a different one."
)
EXPECTED_HINT_UNKNOWN = (
    "See the log field for bore's raw output. "
    "Docs: https://github.com/ekzhang/bore#readme"
)


# ---------------------------------------------------------------------------
# Test Fixtures & Fakes
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_bore_state():
    bore_mod.BORE_STATE["proc"] = None
    bore_mod.BORE_STATE["url"] = ""
    bore_mod.BORE_STATE["log"] = []
    yield
    bore_mod.BORE_STATE["proc"] = None
    bore_mod.BORE_STATE["url"] = ""
    bore_mod.BORE_STATE["log"] = []


class _FakeStdout:
    def __init__(self, lines: list[str]):
        self._lines = list(lines)

    def readline(self) -> str:
        if not self._lines:
            return ""
        return self._lines.pop(0)


class _FakePopen:
    def __init__(
        self,
        lines: list[str] | None = None,
        poll_return: int | None = None,
    ):
        self.stdout = _FakeStdout(lines or [])
        self._poll_return = poll_return
        self.terminated = False
        self.killed = False
        self.waited_timeout = None

    def poll(self) -> int | None:
        return self._poll_return

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: int | None = None) -> int:
        self.waited_timeout = timeout
        return 0

    def kill(self) -> None:
        self.killed = True


# ---------------------------------------------------------------------------
# 1. State and Constants Parity
# ---------------------------------------------------------------------------
def test_bore_state_shape():
    assert set(bore_mod.BORE_STATE.keys()) == {"proc", "url", "log"}
    assert bore_mod.BORE_STATE["proc"] is None
    assert bore_mod.BORE_STATE["url"] == ""
    assert isinstance(bore_mod.BORE_STATE["url"], str)
    assert bore_mod.BORE_STATE["log"] == []


def test_constants_pinned():
    assert bore_mod._URL_WAIT_MIN_SECONDS == EXPECTED_URL_WAIT_MIN
    assert bore_mod._URL_WAIT_MAX_SECONDS == EXPECTED_URL_WAIT_MAX
    assert bore_mod._URL_WAIT_DEFAULT_SECONDS == EXPECTED_URL_WAIT_DEFAULT
    assert bore_mod._URL_WAIT_POLL_INTERVAL_SECONDS == EXPECTED_URL_WAIT_POLL_INTERVAL
    assert bore_mod._ENV_URL_WAIT == EXPECTED_ENV_URL_WAIT
    assert bore_mod._DEFAULT_BORE_SERVER == EXPECTED_DEFAULT_SERVER
    assert bore_mod._DEFAULT_LOCAL_HOST == EXPECTED_DEFAULT_LOCAL_HOST


# ---------------------------------------------------------------------------
# 2. URL Wait Seconds Clamp & Boundary Conditions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw_env,expected",
    [
        (None, 30.0),
        ("", 30.0),
        ("   ", 30.0),
        ("invalid", 30.0),
        ("-10.0", 1.0),
        ("0.0", 1.0),
        ("0.999", 1.0),
        ("1.0", 1.0),
        ("1.0001", 1.0001),
        ("15.5", 15.5),
        ("299.999", 299.999),
        ("300.0", 300.0),
        ("300.001", 300.0),
        ("500.0", 300.0),
    ],
)
def test_url_wait_seconds_boundaries(monkeypatch, raw_env, expected):
    if raw_env is None:
        monkeypatch.delenv(EXPECTED_ENV_URL_WAIT, raising=False)
    else:
        monkeypatch.setenv(EXPECTED_ENV_URL_WAIT, raw_env)
    assert bore_mod._url_wait_seconds() == expected


# ---------------------------------------------------------------------------
# 3. Environment Variable Readers (Server, Local Host, Secret, Remote Port)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "bore.pub"),
        ("", "bore.pub"),
        ("   ", "bore.pub"),
        ("tunnel.acme.org", "tunnel.acme.org"),
        ("  custom.host  ", "custom.host"),
    ],
)
def test_bore_server_parsing(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("ARENA_BORE_SERVER", raising=False)
    else:
        monkeypatch.setenv("ARENA_BORE_SERVER", raw)
    assert bore_mod._bore_server() == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "localhost"),
        ("", "localhost"),
        ("   ", "localhost"),
        ("127.0.0.1", "127.0.0.1"),
        ("  0.0.0.0  ", "0.0.0.0"),
    ],
)
def test_bore_local_host_parsing(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("ARENA_BORE_LOCAL_HOST", raising=False)
    else:
        monkeypatch.setenv("ARENA_BORE_LOCAL_HOST", raw)
    assert bore_mod._bore_local_host() == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("super-secret", "super-secret"),
        ("  token123  ", "token123"),
    ],
)
def test_bore_secret_parsing(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("ARENA_BORE_SECRET", raising=False)
    else:
        monkeypatch.setenv("ARENA_BORE_SECRET", raw)
    assert bore_mod._bore_secret() == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, 0),
        ("", 0),
        ("   ", 0),
        ("invalid", 0),
        ("-1", 0),
        ("0", 0),
        ("1", 1),
        ("80", 80),
        ("8765", 8765),
        ("65535", 65535),
        ("65536", 0),
        ("70000", 0),
    ],
)
def test_bore_remote_port_boundaries(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("ARENA_BORE_REMOTE_PORT", raising=False)
    else:
        monkeypatch.setenv("ARENA_BORE_REMOTE_PORT", raw)
    assert bore_mod._bore_remote_port() == expected


# ---------------------------------------------------------------------------
# 4. System Candidates and Binary Resolution
# ---------------------------------------------------------------------------
def test_system_candidates_windows(monkeypatch):
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Windows")
    assert bore_mod._system_candidates() == EXPECTED_WINDOWS_CANDIDATES


def test_system_candidates_darwin(monkeypatch):
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Darwin")
    assert bore_mod._system_candidates() == EXPECTED_DARWIN_CANDIDATES


def test_system_candidates_linux(monkeypatch):
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Linux")
    assert bore_mod._system_candidates() == EXPECTED_POSIX_CANDIDATES


def test_resolve_bore_which_hit(tmp_path, monkeypatch):
    seen_binary_arg = []

    def _fake_which(binary, cands):
        seen_binary_arg.append(binary)
        if binary == "bore":
            return "/opt/bin/bore"
        return None

    monkeypatch.setattr(bore_mod, "which_windows_or_path", _fake_which)
    bin_path, source = bore_mod._resolve_bore_with_source(tmp_path)
    assert bin_path == "/opt/bin/bore"
    assert source == "system"
    assert seen_binary_arg == ["bore"]


def test_resolve_bore_candidate_file_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(bore_mod, "which_windows_or_path", lambda binary, cands: None)
    monkeypatch.setattr(
        bore_mod, "_system_candidates", lambda: ["/cand1/bore", "/cand2/bore"]
    )

    def _isfile(p):
        return p == "/cand2/bore"

    def _access(p, mode):
        return p == "/cand2/bore" and mode == os.X_OK

    monkeypatch.setattr(bore_mod.os.path, "isfile", _isfile)
    monkeypatch.setattr(bore_mod.os, "access", _access)

    bin_path, source = bore_mod._resolve_bore_with_source(tmp_path)
    assert bin_path == "/cand2/bore"
    assert source == "system"


def test_resolve_bore_candidate_file_not_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(bore_mod, "which_windows_or_path", lambda binary, cands: None)
    monkeypatch.setattr(bore_mod, "_system_candidates", lambda: ["/cand1/bore"])
    monkeypatch.setattr(bore_mod.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(bore_mod.os, "access", lambda p, mode: False)

    bin_path, source = bore_mod._resolve_bore_with_source(tmp_path)
    assert bin_path is None
    assert source == "not_found"


def test_resolve_bore_bundled_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(bore_mod, "which_windows_or_path", lambda binary, cands: None)
    monkeypatch.setattr(bore_mod.os.path, "isfile", lambda p: False)
    bundled = tmp_path / "bore.exe"
    bundled.write_bytes(b"MZ")

    bin_path, source = bore_mod._resolve_bore_with_source(tmp_path)
    assert bin_path == str(bundled)
    assert source == "bundled"


def test_resolve_bore_bundled_posix(tmp_path, monkeypatch):
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bore_mod, "which_windows_or_path", lambda binary, cands: None)
    monkeypatch.setattr(bore_mod.os.path, "isfile", lambda p: False)
    bundled = tmp_path / "bore"
    bundled.write_bytes(b"ELF")

    bin_path, source = bore_mod._resolve_bore_with_source(tmp_path)
    assert bin_path == str(bundled)
    assert source == "bundled"


def test_resolve_bore_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bore_mod, "which_windows_or_path", lambda binary, cands: None)
    monkeypatch.setattr(bore_mod.os.path, "isfile", lambda p: False)

    bin_path, source = bore_mod._resolve_bore_with_source(tmp_path)
    assert bin_path is None
    assert source == "not_found"


# ---------------------------------------------------------------------------
# 5. Version Extraction and Options Forwarding
# ---------------------------------------------------------------------------
class _FakeSubprocessRunResult:
    def __init__(self, stdout: str):
        self.stdout = stdout


def test_get_bore_version_success_and_kwargs(monkeypatch):
    captured_argv = []
    captured_kwargs = {}

    def _fake_run(argv, **kwargs):
        captured_argv.append(list(argv))
        captured_kwargs.update(kwargs)
        return _FakeSubprocessRunResult("bore-cli 0.6.2 (built 2026)")

    monkeypatch.setattr(bore_mod.subprocess, "run", _fake_run)

    version = bore_mod._get_bore_version(
        "/bin/bore", subprocess_kwargs=lambda: {"creationflags": 0x08000000}
    )
    assert version == "0.6.2"
    assert captured_argv == [["/bin/bore", "--version"]]
    assert captured_kwargs == {
        "capture_output": True,
        "text": True,
        "timeout": 5,
        "creationflags": 0x08000000,
    }


@pytest.mark.parametrize(
    "stdout,expected",
    [
        ("bore 0.5.0\n", "0.5.0"),
        ("bore-cli 1.2.34\n", "1.2.34"),
        ("version 10.20.300", "10.20.300"),
        ("unknown binary output", None),
        ("", None),
    ],
)
def test_get_bore_version_regex(monkeypatch, stdout, expected):
    monkeypatch.setattr(
        bore_mod.subprocess, "run", lambda *a, **k: _FakeSubprocessRunResult(stdout)
    )
    assert bore_mod._get_bore_version("/bin/bore") == expected


def test_get_bore_version_handles_exception(monkeypatch):
    def _raise(*a, **k):
        raise OSError("failed to execute")

    monkeypatch.setattr(bore_mod.subprocess, "run", _raise)
    assert bore_mod._get_bore_version("/bin/bore") is None


# ---------------------------------------------------------------------------
# 6. Update Hints Parity
# ---------------------------------------------------------------------------
def test_get_update_hint_system():
    assert (
        bore_mod._get_update_hint("system", "0.6.0") == EXPECTED_SYSTEM_UPDATE_HINT
    )


def test_get_update_hint_bundled():
    assert (
        bore_mod._get_update_hint("bundled", "0.6.0")
        == EXPECTED_BUNDLED_UPDATE_HINT
    )


def test_get_update_hint_not_found_windows(monkeypatch):
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Windows")
    assert (
        bore_mod._get_update_hint("not_found", None)
        == EXPECTED_NOT_FOUND_HINT_WINDOWS
    )


def test_get_update_hint_not_found_darwin(monkeypatch):
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Darwin")
    assert (
        bore_mod._get_update_hint("not_found", None)
        == EXPECTED_NOT_FOUND_HINT_DARWIN
    )


def test_get_update_hint_not_found_posix(monkeypatch):
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Linux")
    assert (
        bore_mod._get_update_hint("not_found", None)
        == EXPECTED_NOT_FOUND_HINT_POSIX
    )


# ---------------------------------------------------------------------------
# 7. Monitor Thread & Listening URL Parsing
# ---------------------------------------------------------------------------
def test_monitor_thread_listening_line_parsing():
    proc = _FakePopen(
        lines=[
            "2026-08-11 INFO bore_cli: connecting\n",
            "2026-08-11 INFO bore_cli: listening at bore.pub:45821\n",
            "2026-08-11 INFO bore_cli: listening at bore.pub:99999\n",  # second line ignored for URL
            "2026-08-11 INFO bore_cli: subsequent connection live\n",  # drained into log
        ]
    )
    bore_mod._bore_monitor_thread(proc, 8765)
    assert bore_mod.BORE_STATE["url"] == "https://bore.pub:45821"
    assert len(bore_mod.BORE_STATE["log"]) == 4
    assert bore_mod.BORE_STATE["log"][-1] == "2026-08-11 INFO bore_cli: subsequent connection live"


def test_monitor_thread_log_cap_at_100():
    lines = [f"log entry {i}\n" for i in range(120)]
    proc = _FakePopen(lines=lines)
    bore_mod._bore_monitor_thread(proc, 8765)
    assert len(bore_mod.BORE_STATE["log"]) == 100
    assert bore_mod.BORE_STATE["log"][0] == "log entry 20"
    assert bore_mod.BORE_STATE["log"][-1] == "log entry 119"


def test_monitor_thread_no_stdout():
    class _NoStdoutProc:
        stdout = None

    bore_mod._bore_monitor_thread(_NoStdoutProc(), 8765)
    assert bore_mod.BORE_STATE["url"] == ""
    assert bore_mod.BORE_STATE["log"] == []


# ---------------------------------------------------------------------------
# 8. Termination Routine
# ---------------------------------------------------------------------------
def test_terminate_bore_default_timeout():
    proc = _FakePopen(poll_return=None)
    bore_mod.BORE_STATE["proc"] = proc
    bore_mod._terminate_bore()
    assert proc.terminated is True
    assert proc.waited_timeout == 5


def test_terminate_bore_alive():
    proc = _FakePopen(poll_return=None)
    bore_mod.BORE_STATE["proc"] = proc
    bore_mod._terminate_bore(timeout=3)
    assert proc.terminated is True
    assert proc.waited_timeout == 3


def test_terminate_bore_already_exited():
    proc = _FakePopen(poll_return=0)
    bore_mod.BORE_STATE["proc"] = proc
    bore_mod._terminate_bore(timeout=3)
    assert proc.terminated is False


def test_terminate_bore_exception_falls_back_to_kill():
    class _FailingProc(_FakePopen):
        def terminate(self):
            raise OSError("permission denied")

    proc = _FailingProc(poll_return=None)
    bore_mod.BORE_STATE["proc"] = proc
    bore_mod._terminate_bore(timeout=2)
    assert proc.killed is True


# ---------------------------------------------------------------------------
# 9. Error Classification Parity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "log_line,expected_code,expected_hint",
    [
        ("authentication failed", "invalid_secret", EXPECTED_HINT_INVALID_SECRET),
        ("invalid secret provided", "invalid_secret", EXPECTED_HINT_INVALID_SECRET),
        ("secret mismatch error", "invalid_secret", EXPECTED_HINT_INVALID_SECRET),
        ("connection refused by remote", "server_unreachable", EXPECTED_HINT_SERVER_UNREACHABLE),
        ("no route to host detected", "server_unreachable", EXPECTED_HINT_SERVER_UNREACHABLE),
        ("dns error resolving bore.pub", "server_unreachable", EXPECTED_HINT_SERVER_UNREACHABLE),
        ("failed to lookup server", "server_unreachable", EXPECTED_HINT_SERVER_UNREACHABLE),
        ("port 8080 is not available", "remote_port_conflict", EXPECTED_HINT_PORT_CONFLICT),
        ("address already in use", "remote_port_conflict", EXPECTED_HINT_PORT_CONFLICT),
        ("random unexplained error", "unknown", EXPECTED_HINT_UNKNOWN),
        ("", "unknown", EXPECTED_HINT_UNKNOWN),
    ],
)
def test_classify_error_exact_patterns(log_line, expected_code, expected_hint):
    code, hint = bore_mod._classify_error([log_line])
    assert code == expected_code
    assert hint == expected_hint


def test_classify_error_multiline_join():
    code, hint = bore_mod._classify_error(["first line", "dns error found", "last line"])
    assert code == "server_unreachable"
    assert hint == EXPECTED_HINT_SERVER_UNREACHABLE


# ---------------------------------------------------------------------------
# 10. _start_bore Execution and State Lifecycle
# ---------------------------------------------------------------------------
def test_start_bore_already_running():
    alive_proc = _FakePopen(poll_return=None)
    bore_mod.BORE_STATE["proc"] = alive_proc
    bore_mod.BORE_STATE["url"] = "https://bore.pub:30000"

    res = bore_mod._start_bore("/bin/bore", 8765, subprocess_kwargs=lambda: {})
    assert res == {
        "ok": True,
        "action": "start",
        "already_running": True,
        "url": "https://bore.pub:30000",
    }


def test_start_bore_spawn_failed(monkeypatch):
    def _raise_popen(*a, **k):
        raise OSError("exec format error")

    monkeypatch.setattr(bore_mod.subprocess, "Popen", _raise_popen)

    res = bore_mod._start_bore("/bin/bore", 8765, subprocess_kwargs=lambda: {})
    assert res == {
        "ok": False,
        "action": "start",
        "error": "exec format error",
        "error_code": "spawn_failed",
    }


def test_start_bore_argv_thread_daemon_and_success(monkeypatch):
    captured = {}
    created_threads = []

    def _fake_popen(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["kwargs"] = dict(kwargs)
        # Return proc that emits listening line immediately
        return _FakePopen(
            lines=["listening at custom.bore.org:44321\n"], poll_return=None
        )

    class _TrackingThread(threading.Thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created_threads.append(self)

    monkeypatch.setattr(bore_mod.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(bore_mod.threading, "Thread", _TrackingThread)
    monkeypatch.setenv("ARENA_BORE_SERVER", "custom.bore.org")
    monkeypatch.setenv("ARENA_BORE_LOCAL_HOST", "127.0.0.1")
    monkeypatch.setenv("ARENA_BORE_SECRET", "s3cr3t")
    monkeypatch.setenv("ARENA_BORE_REMOTE_PORT", "44321")
    monkeypatch.setenv(EXPECTED_ENV_URL_WAIT, "10")

    # Set dirty state prior to start to verify it is reset
    bore_mod.BORE_STATE["url"] = "stale-url"
    bore_mod.BORE_STATE["log"] = ["stale-log"]

    res = bore_mod._start_bore(
        "/bin/bore", 8765, subprocess_kwargs=lambda: {"env": {"FOO": "BAR"}}
    )

    assert captured["argv"] == [
        "/bin/bore",
        "local",
        "8765",
        "--to",
        "custom.bore.org",
        "--local-host",
        "127.0.0.1",
        "--port",
        "44321",
        "--secret",
        "s3cr3t",
    ]
    assert captured["kwargs"]["stdout"] == subprocess.PIPE
    assert captured["kwargs"]["stderr"] == subprocess.STDOUT
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["env"] == {"FOO": "BAR"}
    assert len(created_threads) == 1
    assert created_threads[0].daemon is True

    assert res == {
        "ok": True,
        "action": "start",
        "port": 8765,
        "url": "https://custom.bore.org:44321",
        "server": "custom.bore.org",
        "waited_seconds": 10.0,
        "log": ["listening at custom.bore.org:44321"],
    }


def test_start_bore_process_died_early(monkeypatch):
    timeline = [100.0, 100.0, 101.234]

    def _monotonic():
        return timeline.pop(0) if timeline else 101.234

    monkeypatch.setattr(bore_mod.time, "monotonic", _monotonic)
    monkeypatch.setattr(bore_mod.time, "sleep", lambda s: None)
    monkeypatch.setenv(EXPECTED_ENV_URL_WAIT, "5")

    fake_proc = _FakePopen(
        lines=["connection refused\n"],
        poll_return=1,  # process died
    )

    monkeypatch.setattr(bore_mod.subprocess, "Popen", lambda *a, **k: fake_proc)

    # Set dirty state prior to start to verify it is reset to empty string
    bore_mod.BORE_STATE["url"] = "dirty-stale-url"

    res = bore_mod._start_bore("/bin/bore", 8765, subprocess_kwargs=lambda: {})
    assert res["ok"] is False
    assert res["action"] == "start"
    assert res["error_code"] == "server_unreachable"
    assert res["hint"] == EXPECTED_HINT_SERVER_UNREACHABLE
    assert res["process_died_early"] is True
    assert res["elapsed_seconds"] == 1.23
    assert res["waited_seconds"] == 5.0
    assert res["server"] == EXPECTED_DEFAULT_SERVER
    assert res["log"] == ["connection refused"]
    assert res["error"] == (
        f"bore exited after 1.2s before opening a tunnel. Reason: server_unreachable. {EXPECTED_HINT_SERVER_UNREACHABLE}"
    )
    assert set(res.keys()) == {
        "ok",
        "action",
        "error",
        "error_code",
        "hint",
        "process_died_early",
        "elapsed_seconds",
        "waited_seconds",
        "server",
        "log",
    }
    assert fake_proc.terminated is False
    assert bore_mod.BORE_STATE["proc"] is None
    assert bore_mod.BORE_STATE["url"] == ""
    assert isinstance(bore_mod.BORE_STATE["url"], str)


def test_start_bore_timeout(monkeypatch):
    timeline = [100.0, 105.0, 105.0]

    def _monotonic():
        return timeline.pop(0) if timeline else 105.0

    monkeypatch.setattr(bore_mod.time, "monotonic", _monotonic)
    monkeypatch.setattr(bore_mod.time, "sleep", lambda s: None)
    monkeypatch.setenv(EXPECTED_ENV_URL_WAIT, "5")

    fake_proc = _FakePopen(
        lines=["quiet noise\n"],
        poll_return=None,  # still running
    )

    monkeypatch.setattr(bore_mod.subprocess, "Popen", lambda *a, **k: fake_proc)

    res = bore_mod._start_bore("/bin/bore", 8765, subprocess_kwargs=lambda: {})
    assert res["ok"] is False
    assert res["action"] == "start"
    assert res["error_code"] == "unknown"
    assert res["hint"] == EXPECTED_HINT_UNKNOWN
    assert res["process_died_early"] is False
    assert res["elapsed_seconds"] == 5.0
    assert res["waited_seconds"] == 5.0
    assert res["server"] == EXPECTED_DEFAULT_SERVER
    assert res["log"] == ["quiet noise"]
    assert res["error"] == (
        f"bore timed out generating a tunnel URL after 5.0s. Classifier: unknown. {EXPECTED_HINT_UNKNOWN}"
    )
    assert set(res.keys()) == {
        "ok",
        "action",
        "error",
        "error_code",
        "hint",
        "process_died_early",
        "elapsed_seconds",
        "waited_seconds",
        "server",
        "log",
    }
    assert fake_proc.waited_timeout == 2
    assert bore_mod.BORE_STATE["proc"] is None
    assert bore_mod.BORE_STATE["url"] == ""
    assert isinstance(bore_mod.BORE_STATE["url"], str)


# ---------------------------------------------------------------------------
# 11. bore_action Public Facade Parity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_action",
    ["", "   ", "restart", "invalid", None, 123, []],
)
def test_bore_action_invalid_action(tmp_path, bad_action):
    res = bore_mod.bore_action(
        bad_action, 8765, root_agent=tmp_path, subprocess_kwargs=lambda: {}
    )
    assert res == {"ok": False, "error": "action must be start|stop|status"}


def test_bore_action_start_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bore_mod, "_resolve_bore_with_source", lambda r: (None, "not_found")
    )
    monkeypatch.setattr(bore_mod.platform, "system", lambda: "Linux")

    res = bore_mod.bore_action(
        "start", 8765, root_agent=tmp_path, subprocess_kwargs=lambda: {}
    )
    assert res == {
        "ok": False,
        "error": "bore binary not found",
        "update_hint": EXPECTED_NOT_FOUND_HINT_POSIX,
    }


def test_bore_action_stop(tmp_path):
    proc = _FakePopen(poll_return=None)
    bore_mod.BORE_STATE["proc"] = proc
    bore_mod.BORE_STATE["url"] = "https://bore.pub:12345"

    res = bore_mod.bore_action(
        "STOP", 8765, root_agent=tmp_path, subprocess_kwargs=lambda: {}
    )
    assert res == {"ok": True, "action": "stop"}
    assert proc.terminated is True
    assert bore_mod.BORE_STATE["proc"] is None
    assert bore_mod.BORE_STATE["url"] == ""


def test_bore_action_status_installed_and_running(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bore_mod, "_resolve_bore_with_source", lambda r: ("/bin/bore", "system")
    )
    monkeypatch.setattr(
        bore_mod, "_get_bore_version", lambda b, **k: "0.6.0"
    )
    monkeypatch.setenv("ARENA_BORE_SERVER", "bore.pub")

    proc = _FakePopen(poll_return=None)
    bore_mod.BORE_STATE["proc"] = proc
    bore_mod.BORE_STATE["url"] = "https://bore.pub:32145"
    bore_mod.BORE_STATE["log"] = ["line 1", "line 2"]

    res = bore_mod.bore_action(
        "status", 8765, root_agent=tmp_path, subprocess_kwargs=lambda: {}
    )
    assert res == {
        "ok": True,
        "action": "status",
        "installed": True,
        "source": "system",
        "version": "0.6.0",
        "active": True,
        "url": "https://bore.pub:32145",
        "server": "bore.pub",
        "log": ["line 1", "line 2"],
        "update_hint": EXPECTED_SYSTEM_UPDATE_HINT,
    }


def test_bore_action_status_installed_but_dead_clears_stale_url(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bore_mod, "_resolve_bore_with_source", lambda r: ("/bin/bore", "system")
    )
    monkeypatch.setattr(
        bore_mod, "_get_bore_version", lambda b, **k: "0.6.0"
    )
    monkeypatch.setenv("ARENA_BORE_SERVER", "bore.pub")

    proc = _FakePopen(poll_return=1)  # dead
    bore_mod.BORE_STATE["proc"] = proc
    bore_mod.BORE_STATE["url"] = "https://bore.pub:32145"  # stale url
    bore_mod.BORE_STATE["log"] = ["line 1"]

    res = bore_mod.bore_action(
        "status", 8765, root_agent=tmp_path, subprocess_kwargs=lambda: {}
    )
    assert res == {
        "ok": True,
        "action": "status",
        "installed": True,
        "source": "system",
        "version": "0.6.0",
        "active": False,
        "url": "",
        "server": "bore.pub",
        "log": [],
        "update_hint": EXPECTED_SYSTEM_UPDATE_HINT,
    }
    assert bore_mod.BORE_STATE["url"] == ""


def test_bore_action_status_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bore_mod, "_resolve_bore_with_source", lambda r: (None, "not_found")
    )
    monkeypatch.setenv("ARENA_BORE_SERVER", "bore.pub")

    res = bore_mod.bore_action(
        "status", 8765, root_agent=tmp_path, subprocess_kwargs=lambda: {}
    )
    assert res == {
        "ok": True,
        "action": "status",
        "installed": False,
        "source": "not_found",
        "version": None,
        "active": False,
        "url": "",
        "server": "bore.pub",
        "log": [],
    }
    assert "update_hint" not in res
