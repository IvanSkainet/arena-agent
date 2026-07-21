"""Bridge bootstrap helper extraction tests."""
import logging
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.bootstrap import ensure_session_env, get_bridge_port, load_config_file, resolve_token, setup_logging  # noqa: E402


def test_unified_bootstrap_wrappers_bound_to_bootstrap_module():
    assert ub._ensure_session_env_runtime.__module__ == "arena.bootstrap"
    assert ub._load_config_file_runtime.__module__ == "arena.bootstrap"
    assert ub._get_bridge_port_runtime.__module__ == "arena.bootstrap"
    assert ub._setup_logging_runtime.__module__ == "arena.bootstrap"


def test_get_bridge_port_env(monkeypatch):
    monkeypatch.setenv("ARENA_PORT", "9999")
    assert get_bridge_port() == 9999
    monkeypatch.setenv("ARENA_PORT", "bad")
    assert get_bridge_port() == 8765


def test_load_config_file_json_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    (tmp_path / "bridge.json").write_text('{"port": 1234}', encoding="utf-8")
    # bridge.yml must exist to trigger the historical JSON fallback path.
    (tmp_path / "bridge.yml").write_text("port: 4321", encoding="utf-8")
    cfg = load_config_file(log_info=lambda *args: None, log_debug=lambda *args: None, log_warning=lambda *args: None)
    assert isinstance(cfg, dict)
    assert cfg.get("port") in (1234, 4321)  # PyYAML availability decides path.


def test_setup_logging_returns_arena_bridge_logger(tmp_path):
    logger = setup_logging(app_dir=tmp_path, log_file=tmp_path / "bridge.log")
    assert logger.name == "arena-bridge"
    assert logger.level == logging.DEBUG


def test_resolve_token_priority_and_generation(tmp_path, monkeypatch):
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    token_file = tmp_path / "token.txt"
    assert resolve_token("cli-token", default_token_file=token_file, token_generator=lambda: "generated") == ("cli-token", token_file)

    monkeypatch.setenv("ARENA_LOCAL_BRIDGE_TOKEN", "env-token")
    assert resolve_token(None, default_token_file=token_file, token_generator=lambda: "generated") == ("env-token", token_file)
    monkeypatch.delenv("ARENA_LOCAL_BRIDGE_TOKEN")

    token_file.write_text("file-token-123456789\n", encoding="utf-8")
    assert resolve_token(None, default_token_file=token_file, token_generator=lambda: "generated") == ("file-token-123456789", token_file)

    token_file.unlink()
    tok, path = resolve_token(None, default_token_file=token_file, token_generator=lambda: "generated-token-123456", log_info=lambda *args: None)
    assert tok == "generated-token-123456"
    assert path == token_file
    assert token_file.read_text(encoding="utf-8").strip() == tok


@pytest.mark.skipif(
    os.name != "posix",
    reason="ensure_session_env probes /run/user/UID and X11 sockets that only exist on POSIX; Windows has no getuid()",
)
def test_ensure_session_env_infers_session_type_and_kde(monkeypatch):
    monkeypatch.setattr(os, "name", "posix", raising=False)
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os.path, "isdir", lambda p: p == "/run/user/1000")
    monkeypatch.setattr(os.path, "exists", lambda p: p in {"/run/user/1000/bus", "/tmp/.X11-unix", "/run/user/1000/wayland-0"})
    monkeypatch.setattr(os, "listdir", lambda p: ["X0"] if p == "/tmp/.X11-unix" else [])
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.delenv("DESKTOP_SESSION", raising=False)

    import arena.bootstrap_env as be

    monkeypatch.setattr(be.shutil, "which", lambda cmd: "/usr/bin/qdbus6" if cmd == "qdbus6" else None)

    class _Proc:
        returncode = 0
        stdout = "DP-1\n"

    monkeypatch.setattr(be.subprocess, "run", lambda *args, **kwargs: _Proc())
    ensure_session_env()
    assert os.environ["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert os.environ["DISPLAY"] == ":0"
    assert os.environ["WAYLAND_DISPLAY"] == "wayland-0"
    assert os.environ["XDG_SESSION_TYPE"] == "wayland"
    assert os.environ["XDG_CURRENT_DESKTOP"] == "KDE"
    assert os.environ["DESKTOP_SESSION"] == "KDE"
