"""Unit tests for arena/admin/bore.py (v4.47.0).

Covers:

* URL wait clamp + default.
* Env var readers for server / local_host / secret / remote_port.
* Binary resolution across the three "system" / "bundled" / "not_found"
  outcomes, cross-platform.
* Version extraction.
* Update-hint messages.
* Monitor thread captures the ``listening at <server>:<port>`` line
  and builds the outward-facing ``https://`` URL.
* Error classifier maps the three failure fingerprints we handle.
* ``bore_action("stop"|"status")`` fast paths.
"""
from __future__ import annotations

import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from arena.admin import bore as bore_mod


# ---------------------------------------------------------------------------
# URL wait clamp
# ---------------------------------------------------------------------------
class TestUrlWait:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("ARENA_BORE_URL_WAIT_SECONDS", raising=False)
        assert bore_mod._url_wait_seconds() == 30.0

    def test_default_when_env_empty(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_URL_WAIT_SECONDS", "   ")
        assert bore_mod._url_wait_seconds() == 30.0

    def test_default_when_env_nonnumeric(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_URL_WAIT_SECONDS", "not-a-number")
        assert bore_mod._url_wait_seconds() == 30.0

    def test_clamped_low(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_URL_WAIT_SECONDS", "0.001")
        assert bore_mod._url_wait_seconds() == 1.0

    def test_clamped_high(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_URL_WAIT_SECONDS", "9999")
        assert bore_mod._url_wait_seconds() == 300.0

    def test_passthrough_valid(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_URL_WAIT_SECONDS", "12.5")
        assert bore_mod._url_wait_seconds() == 12.5


# ---------------------------------------------------------------------------
# Env-var readers
# ---------------------------------------------------------------------------
class TestEnvReaders:
    def test_server_default(self, monkeypatch):
        monkeypatch.delenv("ARENA_BORE_SERVER", raising=False)
        assert bore_mod._bore_server() == "bore.pub"

    def test_server_override(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_SERVER", "tunnel.example.com")
        assert bore_mod._bore_server() == "tunnel.example.com"

    def test_server_empty_falls_back(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_SERVER", "   ")
        assert bore_mod._bore_server() == "bore.pub"

    def test_local_host_default(self, monkeypatch):
        monkeypatch.delenv("ARENA_BORE_LOCAL_HOST", raising=False)
        assert bore_mod._bore_local_host() == "localhost"

    def test_local_host_override(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_LOCAL_HOST", "127.0.0.1")
        assert bore_mod._bore_local_host() == "127.0.0.1"

    def test_secret_default(self, monkeypatch):
        monkeypatch.delenv("ARENA_BORE_SECRET", raising=False)
        assert bore_mod._bore_secret() == ""

    def test_secret_passthrough(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_SECRET", "s3cr3t")
        assert bore_mod._bore_secret() == "s3cr3t"

    def test_remote_port_default(self, monkeypatch):
        monkeypatch.delenv("ARENA_BORE_REMOTE_PORT", raising=False)
        assert bore_mod._bore_remote_port() == 0

    def test_remote_port_valid(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_REMOTE_PORT", "12345")
        assert bore_mod._bore_remote_port() == 12345

    def test_remote_port_nonnumeric_falls_back(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_REMOTE_PORT", "abc")
        assert bore_mod._bore_remote_port() == 0

    def test_remote_port_out_of_range_falls_back(self, monkeypatch):
        monkeypatch.setenv("ARENA_BORE_REMOTE_PORT", "99999")
        assert bore_mod._bore_remote_port() == 0
        monkeypatch.setenv("ARENA_BORE_REMOTE_PORT", "-1")
        assert bore_mod._bore_remote_port() == 0


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------
class TestResolve:
    def test_resolve_returns_not_found_when_absent(self, tmp_path, monkeypatch):
        # Force which_windows_or_path to see nothing.
        monkeypatch.setattr(bore_mod, "which_windows_or_path", lambda *_a, **_k: None)
        monkeypatch.setattr(bore_mod.os.path, "isfile", lambda *_: False)
        bin_path, source = bore_mod._resolve_bore_with_source(tmp_path)
        assert bin_path is None
        assert source == "not_found"

    def test_resolve_returns_system_via_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bore_mod, "which_windows_or_path",
                            lambda *_a, **_k: "/usr/bin/bore")
        bin_path, source = bore_mod._resolve_bore_with_source(tmp_path)
        assert bin_path == "/usr/bin/bore"
        assert source == "system"

    def test_resolve_returns_bundled_when_present_in_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bore_mod, "which_windows_or_path", lambda *_a, **_k: None)
        monkeypatch.setattr(bore_mod.os.path, "isfile", lambda *_: False)
        bundled = tmp_path / ("bore.exe" if platform.system() == "Windows" else "bore")
        bundled.write_text("#!/bin/sh\n")
        bin_path, source = bore_mod._resolve_bore_with_source(tmp_path)
        assert bin_path == str(bundled)
        assert source == "bundled"

    def test_system_candidates_shape_per_platform(self, monkeypatch):
        # Windows returns "Program Files" entries.
        monkeypatch.setattr(bore_mod.platform, "system", lambda: "Windows")
        cands = bore_mod._system_candidates()
        assert any("bore.exe" in c for c in cands)
        # Darwin returns homebrew locations.
        monkeypatch.setattr(bore_mod.platform, "system", lambda: "Darwin")
        cands = bore_mod._system_candidates()
        assert "/opt/homebrew/bin/bore" in cands
        # Linux fallback list.
        monkeypatch.setattr(bore_mod.platform, "system", lambda: "Linux")
        cands = bore_mod._system_candidates()
        assert "/usr/local/bin/bore" in cands
        # Cargo prefix included so `cargo install bore-cli` installs are picked up
        # without operator intervention. ``Path.home() / ".cargo/bin/bore"``
        # renders with the OS-native separator, so on Windows the substring
        # is ``.cargo\bin\bore``. Normalise separators for the check.
        cands_norm = [c.replace("\\", "/") for c in cands]
        assert any(".cargo/bin/bore" in c for c in cands_norm)


# ---------------------------------------------------------------------------
# Version + update hint
# ---------------------------------------------------------------------------
class TestVersion:
    def test_get_version_success(self, monkeypatch):
        class _R:
            stdout = "bore 0.6.0\n"
        monkeypatch.setattr(bore_mod.subprocess, "run",
                            lambda *_a, **_k: _R())
        assert bore_mod._get_bore_version("/tmp/bore") == "0.6.0"

    def test_get_version_exception_returns_none(self, monkeypatch):
        def _raise(*_a, **_k):
            raise OSError("boom")
        monkeypatch.setattr(bore_mod.subprocess, "run", _raise)
        assert bore_mod._get_bore_version("/tmp/bore") is None

    def test_get_version_no_match_returns_none(self, monkeypatch):
        class _R:
            stdout = "unrecognised output\n"
        monkeypatch.setattr(bore_mod.subprocess, "run",
                            lambda *_a, **_k: _R())
        assert bore_mod._get_bore_version("/tmp/bore") is None


class TestUpdateHint:
    def test_system_hint_mentions_cargo(self):
        hint = bore_mod._get_update_hint("system", "0.6.0")
        assert "cargo install bore-cli" in hint or "github.com/ekzhang/bore" in hint

    def test_bundled_hint_mentions_script(self):
        hint = bore_mod._get_update_hint("bundled", "0.6.0")
        assert "update_bundled_tools" in hint

    def test_not_found_hint_mentions_install(self, monkeypatch):
        monkeypatch.setattr(bore_mod.platform, "system", lambda: "Linux")
        hint = bore_mod._get_update_hint("not_found", None)
        assert "Install bore" in hint


# ---------------------------------------------------------------------------
# Monitor thread: parse `listening at bore.pub:PORT`
# ---------------------------------------------------------------------------
class _StdoutStub:
    def __init__(self, lines: list[str]):
        self._lines = list(lines)

    def readline(self):
        if not self._lines:
            return ""
        return self._lines.pop(0)


class _ProcStub:
    def __init__(self, lines: list[str]):
        self.stdout = _StdoutStub(lines + [""])

    def poll(self):
        return None


class TestMonitorThread:
    def setup_method(self):
        bore_mod.BORE_STATE["url"] = ""
        bore_mod.BORE_STATE["log"] = []
        bore_mod.BORE_STATE["proc"] = None

    def test_monitor_captures_listening_line(self):
        lines = [
            "some noise before\n",
            "2026-07-17T12:00:00Z  INFO bore_cli::client: connected to server remote_port=35429\n",
            "2026-07-17T12:00:00Z  INFO bore_cli::client: listening at bore.pub:35429\n",
        ]
        proc = _ProcStub(lines)
        bore_mod._bore_monitor_thread(proc, 8765)
        assert bore_mod.BORE_STATE["url"] == "https://bore.pub:35429"
        assert any("listening at" in ln for ln in bore_mod.BORE_STATE["log"])

    def test_monitor_ignores_non_listening_line(self):
        proc = _ProcStub(["just noise\n"])
        bore_mod._bore_monitor_thread(proc, 8765)
        assert bore_mod.BORE_STATE["url"] == ""

    def test_monitor_log_cap_at_100(self):
        lines = [f"line {i}\n" for i in range(150)]
        proc = _ProcStub(lines)
        bore_mod._bore_monitor_thread(proc, 8765)
        assert len(bore_mod.BORE_STATE["log"]) == 100

    def test_monitor_first_listening_wins(self):
        lines = [
            "listening at bore.pub:11111\n",
            "listening at bore.pub:22222\n",
        ]
        proc = _ProcStub(lines)
        bore_mod._bore_monitor_thread(proc, 8765)
        assert bore_mod.BORE_STATE["url"] == "https://bore.pub:11111"


# ---------------------------------------------------------------------------
# Error classifier
# ---------------------------------------------------------------------------
class TestClassifier:
    def test_invalid_secret(self):
        code, hint = bore_mod._classify_error(["authentication failed"])
        assert code == "invalid_secret"
        assert "ARENA_BORE_SECRET" in hint

    def test_server_unreachable(self):
        code, _ = bore_mod._classify_error(["connection refused: bore.pub:7835"])
        assert code == "server_unreachable"

    def test_remote_port_conflict(self):
        code, _ = bore_mod._classify_error(["Port 22 is not available"])
        assert code == "remote_port_conflict"

    def test_unknown_error_returns_unknown_with_generic_hint(self):
        code, hint = bore_mod._classify_error(["blahblahblah"])
        assert code == "unknown"
        assert "docs" in hint.lower() or "github.com/ekzhang/bore" in hint


# ---------------------------------------------------------------------------
# bore_action: dispatch shell
# ---------------------------------------------------------------------------
class TestBoreAction:
    def setup_method(self):
        bore_mod.BORE_STATE["url"] = ""
        bore_mod.BORE_STATE["log"] = []
        bore_mod.BORE_STATE["proc"] = None

    def test_unknown_action_returns_error(self, tmp_path):
        r = bore_mod.bore_action("wibble", 8765, root_agent=tmp_path,
                                 subprocess_kwargs=lambda: {})
        assert r["ok"] is False
        assert "start|stop|status" in r["error"]

    def test_start_when_binary_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bore_mod, "_resolve_bore_with_source",
                            lambda *_a: (None, "not_found"))
        r = bore_mod.bore_action("start", 8765, root_agent=tmp_path,
                                 subprocess_kwargs=lambda: {})
        assert r["ok"] is False
        assert "bore binary not found" in r["error"]
        assert "update_hint" in r

    def test_stop_is_idempotent(self, tmp_path):
        # Nothing running => still returns ok True.
        r = bore_mod.bore_action("stop", 8765, root_agent=tmp_path,
                                 subprocess_kwargs=lambda: {})
        assert r == {"ok": True, "action": "stop"}
        assert bore_mod.BORE_STATE["proc"] is None
        assert bore_mod.BORE_STATE["url"] == ""

    def test_status_when_not_running_and_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bore_mod, "_resolve_bore_with_source",
                            lambda *_a: (None, "not_found"))
        r = bore_mod.bore_action("status", 8765, root_agent=tmp_path,
                                 subprocess_kwargs=lambda: {})
        assert r["ok"] is True
        assert r["installed"] is False
        assert r["active"] is False
        assert r["url"] == ""
        # No update_hint when binary is missing (matches ngrok behaviour).
        assert "update_hint" not in r

    def test_status_clears_stale_url_when_not_running(self, tmp_path, monkeypatch):
        bore_mod.BORE_STATE["url"] = "https://bore.pub:44444"
        monkeypatch.setattr(bore_mod, "_resolve_bore_with_source",
                            lambda *_a: ("/usr/bin/bore", "system"))
        monkeypatch.setattr(bore_mod, "_get_bore_version",
                            lambda *_a: "0.6.0")
        r = bore_mod.bore_action("status", 8765, root_agent=tmp_path,
                                 subprocess_kwargs=lambda: {})
        assert r["active"] is False
        assert r["url"] == ""

    def test_status_reports_server_field(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bore_mod, "_resolve_bore_with_source",
                            lambda *_a: ("/usr/bin/bore", "system"))
        monkeypatch.setattr(bore_mod, "_get_bore_version",
                            lambda *_a: "0.6.0")
        monkeypatch.setenv("ARENA_BORE_SERVER", "self-hosted.example")
        r = bore_mod.bore_action("status", 8765, root_agent=tmp_path,
                                 subprocess_kwargs=lambda: {})
        assert r["server"] == "self-hosted.example"


# ---------------------------------------------------------------------------
# _start_bore: spawn failure path
# ---------------------------------------------------------------------------
class TestStartBore:
    def setup_method(self):
        bore_mod.BORE_STATE["url"] = ""
        bore_mod.BORE_STATE["log"] = []
        bore_mod.BORE_STATE["proc"] = None

    def test_start_returns_error_when_popen_raises(self, monkeypatch):
        def _boom(*_a, **_k):
            raise OSError("no exec bit")
        monkeypatch.setattr(bore_mod.subprocess, "Popen", _boom)
        r = bore_mod._start_bore("/tmp/bore", 8765,
                                 subprocess_kwargs=lambda: {})
        assert r["ok"] is False
        assert r["error_code"] == "spawn_failed"

    def test_start_returns_already_running_when_proc_alive(self, monkeypatch):
        class _AliveProc:
            def poll(self):
                return None
        bore_mod.BORE_STATE["proc"] = _AliveProc()
        bore_mod.BORE_STATE["url"] = "https://bore.pub:11111"
        r = bore_mod._start_bore("/tmp/bore", 8765,
                                 subprocess_kwargs=lambda: {})
        assert r["ok"] is True
        assert r["already_running"] is True
        assert r["url"] == "https://bore.pub:11111"
        # Reset for next test.
        bore_mod.BORE_STATE["proc"] = None


# ---------------------------------------------------------------------------
# secret + remote_port are threaded into argv only when configured
# ---------------------------------------------------------------------------
class TestArgvShape:
    def setup_method(self):
        bore_mod.BORE_STATE["url"] = ""
        bore_mod.BORE_STATE["log"] = []
        bore_mod.BORE_STATE["proc"] = None

    def test_secret_added_when_env_set(self, monkeypatch):
        captured = {}

        class _FakeProc:
            stdout = _StdoutStub(["listening at bore.pub:12345\n", ""])
            def poll(self): return None
            def terminate(self): pass
            def wait(self, timeout=None): return 0
            def kill(self): pass

        def _fake_popen(argv, **_k):
            captured["argv"] = argv
            return _FakeProc()

        monkeypatch.setenv("ARENA_BORE_SECRET", "top-secret")
        monkeypatch.setenv("ARENA_BORE_REMOTE_PORT", "31337")
        monkeypatch.setenv("ARENA_BORE_URL_WAIT_SECONDS", "5")
        monkeypatch.setattr(bore_mod.subprocess, "Popen", _fake_popen)
        # Skip the sleep-based poll loop -- the monitor thread will
        # publish the URL from the very first readline().
        _ = bore_mod._start_bore("/tmp/bore", 8765,
                                 subprocess_kwargs=lambda: {})
        argv = captured["argv"]
        # bore local <port> --to <server> --local-host <h> --port <N> --secret <S>
        assert argv[0] == "/tmp/bore"
        assert argv[1] == "local"
        assert argv[2] == "8765"
        assert "--to" in argv
        assert "--secret" in argv
        assert "top-secret" in argv
        assert "--port" in argv
        assert "31337" in argv

    def test_secret_omitted_when_env_unset(self, monkeypatch):
        captured = {}

        class _FakeProc:
            stdout = _StdoutStub(["listening at bore.pub:12345\n", ""])
            def poll(self): return None
            def terminate(self): pass
            def wait(self, timeout=None): return 0
            def kill(self): pass

        def _fake_popen(argv, **_k):
            captured["argv"] = argv
            return _FakeProc()

        monkeypatch.delenv("ARENA_BORE_SECRET", raising=False)
        monkeypatch.setenv("ARENA_BORE_URL_WAIT_SECONDS", "5")
        monkeypatch.setattr(bore_mod.subprocess, "Popen", _fake_popen)
        _ = bore_mod._start_bore("/tmp/bore", 8765,
                                 subprocess_kwargs=lambda: {})
        argv = captured["argv"]
        assert "--secret" not in argv
