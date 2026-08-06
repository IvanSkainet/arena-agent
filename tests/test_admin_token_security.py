"""Executable security contract for admin token regeneration.

The old helper was almost untested: it wrote directly through the target
path, followed symlinks, and reported success when chmod failed. These tests
exercise the filesystem contract rather than only checking that a string was
returned.
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena import token_storage  # noqa: E402
from arena.admin import token as token_module  # noqa: E402


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_regenerate_uses_default_path_and_owner_only_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    target = tmp_path / "default" / "nested" / "token.txt"

    result = token_module.token_regenerate(default_token_file=target)

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == result["token"]
    assert len(result["token"]) == 43  # 32 random bytes, unpadded URL-safe base64
    assert "Existing connections" in result["note"]
    assert "POST /v1/restart" in result["note"]
    if os.name != "nt":
        assert _mode(target) == 0o600


def test_regenerate_honors_non_empty_env_path(tmp_path, monkeypatch):
    env_target = tmp_path / "from-env" / "token.txt"
    default_target = tmp_path / "default.txt"
    monkeypatch.setenv("ARENA_TOKEN_FILE", str(env_target))

    result = token_module.token_regenerate("", default_token_file=default_target)

    assert result["ok"] is True
    assert env_target.exists()
    assert not default_target.exists()
    assert result["written_to"] == [str(env_target)]


def test_whitespace_only_env_path_falls_back_to_default(tmp_path, monkeypatch):
    default_target = tmp_path / "default.txt"
    monkeypatch.setenv("ARENA_TOKEN_FILE", "   ")

    result = token_module.token_regenerate("", default_token_file=default_target)

    assert result["ok"] is True
    assert default_target.exists()


def test_token_bytes_are_encoded_without_changing_the_entropy_shape(tmp_path, monkeypatch):
    raw = bytes(range(32))
    monkeypatch.setattr(token_module.secrets, "token_bytes", lambda size: raw if size == 32 else b"x" * size)
    target = tmp_path / "token.txt"

    result = token_module.token_regenerate(str(target), default_token_file=target)

    expected = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert result["ok"] is True
    assert result["token"] == expected
    assert len(result["token"]) == 43


def test_regenerate_does_not_follow_a_symlink_target(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("must-survive", encoding="utf-8")
    target = tmp_path / "token.txt"
    try:
        target.symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this runner")

    result = token_module.token_regenerate(str(target), default_token_file=target)

    assert result["ok"] is False
    assert "token" not in result
    assert "symlink" in result["error"]
    assert victim.read_text(encoding="utf-8") == "must-survive"
    assert target.is_symlink()


def test_chmod_failure_is_reported_as_failure(tmp_path, monkeypatch):
    target = tmp_path / "token.txt"

    def denied(*_args, **_kwargs):
        raise OSError("chmod denied")

    monkeypatch.setattr(token_storage.os, "chmod", denied)
    result = token_module.token_regenerate(str(target), default_token_file=target)

    assert result["ok"] is False
    assert "token" not in result
    assert result["error"].startswith("Failed to write")
    assert not target.exists()
    assert not list(tmp_path.glob(".token.txt.*.tmp"))


def test_atomic_replace_failure_preserves_the_previous_token(tmp_path, monkeypatch):
    target = tmp_path / "token.txt"
    target.write_text("old-token", encoding="utf-8")

    def denied(*_args, **_kwargs):
        raise OSError("replace denied")

    monkeypatch.setattr(token_storage.os, "replace", denied)
    result = token_module.token_regenerate(str(target), default_token_file=target)

    assert result["ok"] is False
    assert result["error"].startswith("Failed to write")
    assert target.read_text(encoding="utf-8") == "old-token"
    assert not list(tmp_path.glob(".token.txt.*.tmp"))


def test_parent_write_failure_is_a_structured_refusal(tmp_path):
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("x", encoding="utf-8")

    result = token_module.token_regenerate(
        str(parent_file / "token.txt"), default_token_file=tmp_path / "default.txt"
    )

    assert result["ok"] is False
    assert result["error"].startswith("Failed to write")
    assert "token" not in result
