"""Tests for cloudflared autostart persistence (v4.22.1).

Covers marker file lifecycle, env-var opt-in, and the
``run_autostart`` orchestrator that ties them together with the
real ``cloudflared_funnel_action`` code path.

Design note: this module deliberately does *not* spawn a real
cloudflared subprocess. The orchestrator is invoked with a stub
``cloudflared_funnel_action_fn`` that records the call arguments,
so we prove the wiring end-to-end without needing cloudflared
installed in CI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from arena.admin.cloudflared_autostart import (
    AutostartOutcome,
    ENV_VAR,
    MARKER_FILENAME,
    is_env_enabled,
    mark_autostart,
    marker_path,
    run_autostart,
    should_autostart,
    unmark_autostart,
)


# ---------------------------------------------------------------------------
# marker file lifecycle
# ---------------------------------------------------------------------------
def test_marker_path_is_inside_root_agent(tmp_path):
    p = marker_path(tmp_path)
    assert p == tmp_path / MARKER_FILENAME
    assert p.parent == tmp_path


def test_mark_autostart_creates_marker_with_payload(tmp_path):
    p = mark_autostart(tmp_path, port=8765)
    assert p.exists()
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["port"] == 8765
    assert payload["version"] == 1
    assert isinstance(payload["marked_at"], int)
    assert payload["marked_at"] > 0


def test_mark_autostart_is_idempotent(tmp_path):
    """Calling twice overwrites — never appends garbage. Second
    call still yields a valid JSON marker with the latest port."""
    mark_autostart(tmp_path, port=8765)
    mark_autostart(tmp_path, port=9000)
    payload = json.loads((tmp_path / MARKER_FILENAME).read_text())
    assert payload["port"] == 9000


def test_mark_autostart_uses_atomic_rename(tmp_path):
    """Atomic write leaves no *.tmp files after a normal run."""
    mark_autostart(tmp_path, port=8765)
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_unmark_removes_existing_marker(tmp_path):
    mark_autostart(tmp_path, port=8765)
    assert unmark_autostart(tmp_path) is True
    assert not (tmp_path / MARKER_FILENAME).exists()


def test_unmark_missing_marker_is_a_noop(tmp_path):
    """rm -f semantics — no file, no error, return False."""
    assert unmark_autostart(tmp_path) is False


# ---------------------------------------------------------------------------
# env var + should_autostart
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("TRUE", True),
    ("yes", True), ("YES", True), ("on", True), ("On", True),
    ("0", False), ("false", False), ("no", False),
    ("", False), ("   ", False), ("garbage", False),
])
def test_env_var_truthy_shapes(monkeypatch, val, expected):
    monkeypatch.setenv(ENV_VAR, val)
    assert is_env_enabled() is expected


def test_env_var_unset_is_false(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert is_env_enabled() is False


def test_should_autostart_marker_alone(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    mark_autostart(tmp_path, port=8765)
    assert should_autostart(tmp_path) is True


def test_should_autostart_env_alone(tmp_path, monkeypatch):
    """Env var alone is enough — a clean install with no marker
    still autostarts when the operator sets the env explicitly."""
    monkeypatch.setenv(ENV_VAR, "1")
    assert should_autostart(tmp_path) is True


def test_should_autostart_neither_signal(tmp_path, monkeypatch):
    """Fresh install, no marker, no env — never autostarts."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert should_autostart(tmp_path) is False


# ---------------------------------------------------------------------------
# run_autostart orchestrator
# ---------------------------------------------------------------------------
def _stub_ok(url="https://stub.trycloudflare.com"):
    calls = []
    def _fn(action, port, **kwargs):
        calls.append({"action": action, "port": port, **kwargs})
        return {"ok": True, "url": url}
    return _fn, calls


def _stub_fail(error="binary missing"):
    calls = []
    def _fn(action, port, **kwargs):
        calls.append({"action": action, "port": port, **kwargs})
        return {"ok": False, "error": error}
    return _fn, calls


def _stub_raises(exc=RuntimeError("boom")):
    def _fn(action, port, **kwargs):
        raise exc
    return _fn


def _empty_kwargs():
    return {}


def test_run_autostart_no_marker_no_env_does_not_attempt(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    fn, calls = _stub_ok()
    outcome = run_autostart(
        root_agent=tmp_path, port=8765,
        cloudflared_funnel_action_fn=fn,
        subprocess_kwargs_fn=_empty_kwargs,
    )
    assert outcome.attempted is False
    assert outcome.ok is False
    assert calls == []


def test_run_autostart_with_marker_calls_start(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    mark_autostart(tmp_path, port=8765)
    fn, calls = _stub_ok(url="https://xyz.trycloudflare.com")
    outcome = run_autostart(
        root_agent=tmp_path, port=8765,
        cloudflared_funnel_action_fn=fn,
        subprocess_kwargs_fn=_empty_kwargs,
    )
    assert outcome.attempted is True
    assert outcome.ok is True
    assert outcome.url == "https://xyz.trycloudflare.com"
    assert outcome.reason == "started"
    assert len(calls) == 1
    assert calls[0]["action"] == "start"
    assert calls[0]["port"] == 8765
    assert calls[0]["root_agent"] == tmp_path
    assert calls[0]["subprocess_kwargs"] is _empty_kwargs


def test_run_autostart_with_env_only_calls_start(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    fn, calls = _stub_ok()
    outcome = run_autostart(
        root_agent=tmp_path, port=8765,
        cloudflared_funnel_action_fn=fn,
        subprocess_kwargs_fn=_empty_kwargs,
    )
    assert outcome.attempted is True
    assert outcome.ok is True
    assert len(calls) == 1


def test_run_autostart_reports_failure_reason(tmp_path, monkeypatch):
    """When cloudflared_funnel_action returns ok:false, the outcome
    surfaces the error string so the log line is diagnosable."""
    monkeypatch.setenv(ENV_VAR, "1")
    fn, _ = _stub_fail("no binary")
    outcome = run_autostart(
        root_agent=tmp_path, port=8765,
        cloudflared_funnel_action_fn=fn,
        subprocess_kwargs_fn=_empty_kwargs,
    )
    assert outcome.attempted is True
    assert outcome.ok is False
    assert "no binary" in outcome.reason


def test_run_autostart_swallows_exceptions(tmp_path, monkeypatch):
    """A raise inside cloudflared_funnel_action must not crash the
    bridge boot — the outcome captures the exception in ``reason``."""
    monkeypatch.setenv(ENV_VAR, "1")
    fn = _stub_raises(RuntimeError("boom"))
    outcome = run_autostart(
        root_agent=tmp_path, port=8765,
        cloudflared_funnel_action_fn=fn,
        subprocess_kwargs_fn=_empty_kwargs,
    )
    assert outcome.attempted is True
    assert outcome.ok is False
    assert "RuntimeError" in outcome.reason
    assert "boom" in outcome.reason


def test_run_autostart_measures_duration(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "1")
    fn, _ = _stub_ok()
    outcome = run_autostart(
        root_agent=tmp_path, port=8765,
        cloudflared_funnel_action_fn=fn,
        subprocess_kwargs_fn=_empty_kwargs,
    )
    assert outcome.duration_sec >= 0.0
    assert outcome.duration_sec < 5.0  # stub returns instantly


# ---------------------------------------------------------------------------
# Regression: marker file must NEVER live under /tmp
# (v4.22.1 lesson from the workspace-sandbox rules).
# ---------------------------------------------------------------------------
def test_marker_never_lives_under_tmp(tmp_path):
    """The marker path is a pure function of ``root_agent`` — it
    never escapes to /tmp/ or hard-codes a system-global path."""
    p = marker_path(tmp_path)
    resolved = str(p.resolve())
    assert "/tmp/" not in resolved or str(tmp_path.resolve()).startswith("/tmp/")
    # Explicit: what we return is always inside the root we asked for.
    assert p.is_relative_to(tmp_path)
