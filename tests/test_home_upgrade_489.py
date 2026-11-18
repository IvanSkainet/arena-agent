"""Final-integration upgrade, late configuration and executable wiring guards."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

import pytest

from arena import home, runtime_profile

CHECK = TestCase()


@pytest.fixture
def locations(tmp_path, monkeypatch):
    code, state = tmp_path / "code", tmp_path / "state"
    code.mkdir()
    state.mkdir()
    monkeypatch.delenv("ARENA_AGENT_HOME", raising=False)
    monkeypatch.delenv("ARENA_TOKEN_FILE", raising=False)
    monkeypatch.setattr(home, "code_root", lambda: code)
    monkeypatch.setattr(home, "default_home", lambda: state)
    return code, state


def test_fresh_install_does_not_write_state_in_code(locations):
    code, state = locations
    (code / "missions/templates").mkdir(parents=True)
    (code / "missions/templates/example.json").write_text("{}")
    CHECK.assertEqual(home.agent_home(), state)


@pytest.mark.parametrize("relative", ["memory/facts.db", "memory/facts.jsonl", "webhooks.json",
                                      "queue/inbox/a.json", "missions/a.json", "relay/inbox/a.json"])
def test_upgrade_keeps_legacy_state_reachable(locations, relative):
    code, _ = locations
    old = code / relative
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("existing data")
    CHECK.assertEqual(home.agent_home(), code)
    CHECK.assertEqual(old.read_text(), "existing data")


def test_ambiguous_split_state_requires_explicit_choice(locations, monkeypatch):
    code, state = locations
    for root in (code, state):
        (root / "webhooks.json").write_text("{}")
    with pytest.raises(RuntimeError, match="ARENA_AGENT_HOME"):
        home.agent_home()
    monkeypatch.setenv("ARENA_AGENT_HOME", str(state))
    CHECK.assertEqual(home.agent_home(), state)


def test_existing_token_is_migrated_without_changing_credential(locations, monkeypatch):
    from arena import bootstrap_token

    code, state = locations
    legacy = code / "token.txt"
    secret = "legacy-credential-unchanged-123456"
    legacy.write_text(secret)
    monkeypatch.setattr(bootstrap_token, "code_root", lambda: code)
    token, write_path = bootstrap_token.resolve_token(
        None, default_token_file=legacy,
        token_generator=lambda: CHECK.fail("upgrade generated a different credential"))
    CHECK.assertEqual(token, secret)
    CHECK.assertEqual(write_path, state / "token.txt")
    CHECK.assertEqual(write_path.read_text().strip(), secret)
    CHECK.assertEqual(home.token_path(), write_path)


def test_published_config_view_is_live_but_readonly():
    cfg = {"root": "/first", "profile": "cautious"}
    runtime_profile.publish(cfg)
    try:
        view = runtime_profile.current_config()
        with pytest.raises(TypeError):
            view["profile"] = "owner-shell"
        cfg["root"] = "/second"
        CHECK.assertEqual(view["root"], "/second")
    finally:
        runtime_profile.reset_for_tests()


def test_task_default_cwd_is_read_after_configuration(tmp_path):
    from arena.tasks.runtime import TaskQueueRuntimeContext, make_task_queue_runtime

    ctx = TaskQueueRuntimeContext(inbox=tmp_path / "inbox", running=tmp_path / "running",
                                  done=tmp_path / "done", failed=tmp_path / "failed",
                                  default_cwd=lambda: str(home.sandbox_home()), now=lambda: "now")
    runtime = make_task_queue_runtime(ctx)
    workspace = tmp_path / "late-workspace"
    runtime_profile.publish({"root": str(workspace)})
    try:
        result = runtime.task_submit_sync({"cmd": "echo test"})
        CHECK.assertEqual(result["task"]["cwd"], str(workspace))
    finally:
        runtime_profile.reset_for_tests()


def test_watch_default_root_is_read_after_configuration(tmp_path):
    from arena.filewatch.runtime import FileWatchRuntimeContext, make_file_watch_runtime

    workspace = tmp_path / "late-workspace"
    workspace.mkdir()
    (workspace / "readme.txt").write_text("complete")
    ctx = FileWatchRuntimeContext(home=tmp_path / "different-home", default_root=home.sandbox_home,
                                  emit_event=lambda *args: None, utc_now=lambda: "now",
                                  log_info=lambda *args: None, log_warning=lambda *args: None)
    runtime = make_file_watch_runtime(ctx)
    runtime_profile.publish({"root": str(workspace)})
    try:
        result = runtime.add_sync(path="readme.txt")
        CHECK.assertTrue(result["ok"], result)
    finally:
        runtime_profile.reset_for_tests()


def test_cli_run_bin_uses_real_code_path(monkeypatch):
    from arena.agentctl_cli import agentctl_common as cli

    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kwargs: calls.append(argv))
    cli.run_bin("mcp_marketplace.py", ["list"])
    CHECK.assertEqual(calls, [[sys.executable, str(cli.code_root() / "bin/mcp_marketplace.py"), "list"]])


def test_missing_source_scripts_dispatch_to_packaged_modules(tmp_path, monkeypatch):
    from arena.agentctl_cli import agentctl_common as cli

    calls = []
    monkeypatch.setattr(cli, "BIN", tmp_path)
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kwargs: calls.append(argv))
    cli.run_bin("mcp_marketplace.py", ["list"])
    cli.run_bin("subagent.py", ["list"])
    CHECK.assertEqual(calls, [[sys.executable, "-m", "arena.mcp_marketplace.cli", "list"],
                              [sys.executable, "-m", "arena.subagent_cli", "list"]])


def test_worker_entry_point_runs_from_unrelated_cwd(tmp_path, monkeypatch):
    """The worker itself is packaged, not a missing site-packages/scripts file."""
    from arena.inventory import slow_probe_cache

    directory = tmp_path / "cache"
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path),
           "ARENA_AGENT_HOME": str(tmp_path / "state")}
    worker = Path(slow_probe_cache.__file__).with_name("cache_worker.py")
    subprocess.run([sys.executable, "-I", str(worker), "python_venvs", str(directory)],
                   cwd=tmp_path, env=env, check=True, timeout=15)
    raw = json.loads((directory / "python_venvs.json").read_text())
    CHECK.assertEqual(raw["result"]["venvs"], [])


def test_new_files_do_not_move_a_running_process_to_another_store(locations):
    code, state = locations
    CHECK.assertEqual(home.agent_home(), state)
    (code / "webhooks.json").write_text("{}")
    CHECK.assertEqual(home.agent_home(), state)


def test_packaged_mcp_cli_really_executes_the_dispatcher(tmp_path):
    env = {**os.environ, "ARENA_AGENT_HOME": str(tmp_path)}
    result = subprocess.run([sys.executable, "-m", "arena.mcp_marketplace.cli", "list"],
                            env=env, capture_output=True, text=True, check=True, timeout=10)
    CHECK.assertEqual(json.loads(result.stdout), {"mcpServers": {}})
