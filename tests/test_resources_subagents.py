"""Subagent helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.resources.subagents import spawn_subagent  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_spawn_subagent_missing_script(tmp_path):
    res = spawn_subagent({"cmd": "echo hi", "timeout": 1}, bin_dir=tmp_path / "bin", subprocess_kwargs_fn=lambda: {})
    assert res["ok"] is False
    assert "stderr" in res


def test_unified_bridge_subagent_wrapper_callable():
    assert callable(ub._subagents_spawn_sync)
