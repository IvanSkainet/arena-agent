"""Bridge bootstrap helper extraction tests."""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.bootstrap import get_bridge_port, load_config_file, setup_logging  # noqa: E402


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
