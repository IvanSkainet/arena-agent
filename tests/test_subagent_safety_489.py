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


@pytest.mark.parametrize("wait", [False, True])
def test_subagent_timeout_finishes_metadata_and_reaps_command_tree(cli, tmp_path, monkeypatch, wait):
    import os
    import shlex
    import subprocess
    import sys
    import time

    import psutil

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    marker = tmp_path / "pids.json"
    script = tmp_path / "child.py"
    script.write_text(
        "import subprocess,sys,os,json,time\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
        f"Path({str(marker)!r}).write_text(json.dumps([os.getpid(),child.pid]))\n"
        "time.sleep(60)\n")
    argv = [sys.executable, str(script)]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    result = cli.spawn(SimpleNamespace(cmd=command, name="timeout-test", timeout=1,
                                      wait=wait, max_out=10))
    assert result == (1 if wait else 0)
    run = next(cli.SUB_DIR.iterdir())
    deadline = time.monotonic() + 20
    pids = []
    try:
        while time.monotonic() < deadline:
            meta = json.loads((run / "meta.json").read_text())
            if meta["status"] == "timeout":
                break
            time.sleep(.03)
        assert meta["status"] == "timeout"
        assert json.loads((run / "summary.json").read_text())["status"] == "timeout"
        pids = json.loads(marker.read_text())
        assert not any(psutil.pid_exists(pid) for pid in pids)
    finally:
        if marker.exists():
            pids = json.loads(marker.read_text())
        for pid in pids:
            try:
                psutil.Process(pid).kill()
            except psutil.NoSuchProcess:
                pass


def test_subagent_output_is_private_even_with_a_permissive_umask(tmp_path):
    import os
    import stat

    from arena.subagent_lifecycle import _private_output, output_tail

    path = tmp_path / "stdout.log"
    old = os.umask(0)
    try:
        with _private_output(path) as stream:
            stream.write(b"private output\n")
    finally:
        os.umask(old)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert output_tail(path, 0) == ""
