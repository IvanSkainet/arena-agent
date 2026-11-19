"""Destructive subagent maintenance must not escape or delete active work."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    from arena import subagent_cli

    monkeypatch.setattr(subagent_cli, "SUB_DIR", tmp_path / "subagents")
    subagent_cli.SUB_DIR.mkdir(exist_ok=True)
    return subagent_cli


def test_rm_refuses_traversal_and_absolute_paths(cli, tmp_path):
    outside = tmp_path / "operator-data"
    outside.mkdir()
    marker = outside / "keep"
    marker.write_text("preserve")
    for run_id in ("../operator-data", str(outside), "..", ""):
        assert cli.rm_cmd(SimpleNamespace(id=run_id)) == 1
        assert marker.read_text() == "preserve"


def test_prune_and_rm_preserve_active_and_unknown_runs(cli):
    for run_id, status in (("a" * 10, "spawned"), ("b" * 10, "ok"), ("c" * 10, None)):
        run = cli.SUB_DIR / run_id
        run.mkdir()
        if status:
            (run / "meta.json").write_text(json.dumps({"status": status}))
    assert cli.rm_cmd(SimpleNamespace(id="a" * 10)) == 1
    assert cli.prune_cmd(SimpleNamespace(keep=0)) == 0
    assert (cli.SUB_DIR / ("a" * 10)).exists()
    assert (cli.SUB_DIR / ("c" * 10)).exists()
    assert not (cli.SUB_DIR / ("b" * 10)).exists()
