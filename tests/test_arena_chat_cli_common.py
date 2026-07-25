"""Unit tests for arena.chat_cli.common (v4.79.0 coverage lift).

The module provides the small utility helpers used by the
modular chat REPL (timestamps, slug generation, JSONL event
writes). Until v4.79.0 it had 0% line coverage (71 statements,
8 branches, never imported by any test). These tests focus on
the pure functions; the ``fcntl``-protected ``write_event``
path is exercised on Linux only.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


# chat_cli.common does ``os.umask(0o077)`` and binds HOME at
# import time based on ARENA_AGENT_HOME. We point it at a
# tmp path so we don't touch the real bridge.
_tmp_home = Path(tempfile.mkdtemp(prefix="arena_chat_cli_test_"))
os.environ["ARENA_AGENT_HOME"] = str(_tmp_home)

from arena.chat_cli import common as chat_common  # noqa: E402


# --------------------------------------------------------------------
# now_iso
# --------------------------------------------------------------------
def test_now_iso_returns_utc_with_seconds_precision():
    out = chat_common.now_iso()
    # Always ends in +00:00 because we ask for tz=UTC.
    assert out.endswith("+00:00")
    # YYYY-MM-DDTHH:MM:SS+00:00 -> 25 chars.
    assert len(out) == 25
    # First 19 chars are an ISO-8601 datetime (no fractional seconds).
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", out[:19])


# --------------------------------------------------------------------
# slugify
# --------------------------------------------------------------------
def test_slugify_lowercases_and_replaces_whitespace():
    assert chat_common.slugify("Hello World") == "hello-world"


def test_slugify_collapses_repeated_non_alnum_into_single_dash():
    assert chat_common.slugify("foo   ---   bar") == "foo-bar"


def test_slugify_strips_leading_and_trailing_dashes():
    assert chat_common.slugify("---trim---") == "trim"


def test_slugify_truncates_to_40_chars():
    long = "a" * 80
    out = chat_common.slugify(long)
    assert len(out) == 40


def test_slugify_returns_session_when_input_is_empty_or_punctuation():
    # slugify("") -> "".strip("-") -> "" -> fall back to "session"
    assert chat_common.slugify("") == "session"
    # slugify("   ") -> "" -> "session"
    assert chat_common.slugify("   ") == "session"
    # slugify("---") -> "" -> "session"
    assert chat_common.slugify("---") == "session"


def test_slugify_handles_unicode_by_dropping_non_alnum():
    # Anything outside [a-zA-Z0-9] becomes a single dash.
    out = chat_common.slugify("café latte")
    assert out == "caf-latte"


# --------------------------------------------------------------------
# write_event
# --------------------------------------------------------------------
def test_write_event_appends_jsonl_line(tmp_path):
    path = tmp_path / "session.jsonl"
    chat_common.write_event(path, role="user", kind="msg", content="hi")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["role"] == "user"
    assert rec["kind"] == "msg"
    assert rec["content"] == "hi"
    # ts must be present and ISO-8601
    assert rec["ts"].endswith("+00:00")


def test_write_event_includes_meta_when_provided(tmp_path):
    path = tmp_path / "session.jsonl"
    chat_common.write_event(
        path, role="agent", kind="tool", content="ok",
        tool="browser.search", exit_code=0,
    )
    rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["meta"] == {"tool": "browser.search", "exit_code": 0}


def test_write_event_concurrent_safe_appends(tmp_path):
    # On Linux the flock path is taken; on other platforms the
    # fcntl import is monkey-skipped. We just verify the file
    # ends with a single newline-terminated JSON object.
    path = tmp_path / "session.jsonl"
    chat_common.write_event(path, role="user", kind="msg", content="x")
    raw = path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert json.loads(raw.strip())["content"] == "x"


# --------------------------------------------------------------------
# open_session
# --------------------------------------------------------------------
def test_open_session_creates_jsonl_in_sessions_dir(monkeypatch, tmp_path):
    # Redirect SESS_DIR to tmp_path so we don't touch the real
    # bridge. Re-import the constants via monkeypatching the
    # module-level SESS_DIR.
    monkeypatch.setattr(chat_common, "SESS_DIR", tmp_path)
    monkeypatch.setattr(chat_common, "CURRENT", tmp_path / "current")
    p = chat_common.open_session("test session")
    assert p.exists()
    assert p.name.endswith(".jsonl")
    assert "test-session" in p.name


def test_open_session_uses_default_name_when_none(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_common, "SESS_DIR", tmp_path)
    monkeypatch.setattr(chat_common, "CURRENT", tmp_path / "current")
    p = chat_common.open_session(None)
    assert "chat" in p.name
    assert p.exists()
