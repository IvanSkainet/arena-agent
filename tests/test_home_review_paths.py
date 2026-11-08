"""Regression checks for state/code separation when the home is relocated."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_memory_mcp_uses_state_home_not_workspace(tmp_path, monkeypatch):
    from arena.mcp.tool_memory_export_import import _get_db_path
    home, workspace = tmp_path / "state", tmp_path / "workspace"
    monkeypatch.setenv("ARENA_AGENT_HOME", str(home))

    class Context:
        def app_config(self):
            return {"root": str(workspace)}

    assert _get_db_path(Context()) == home / "memory" / "facts.db"


def test_mission_and_skills_execute_hooks_only_from_code_root(tmp_path, monkeypatch):
    from arena.missions_cli import common as missions
    from arena.skills import cli_common as skills
    home, code = tmp_path / "state", tmp_path / "code"
    for root in (home, code):
        (root / "bin").mkdir(parents=True)
        (root / "bin" / "hooks_runner.py").touch()
    monkeypatch.setenv("ARENA_AGENT_HOME", str(home))
    monkeypatch.setattr(missions, "code_root", lambda: code, raising=False)
    monkeypatch.setattr(skills, "code_root", lambda: code, raising=False)
    monkeypatch.setattr(skills, "ROOT", home)
    calls = []
    monkeypatch.setattr("subprocess.run", lambda args, **kw: calls.append(args))
    missions._fire_mission_hook("start", "x")
    skills._fire_hook("start", "x")
    assert len(calls) == 2
    assert all(Path(args[1]) == code / "bin" / "hooks_runner.py" for args in calls)


def test_cli_executables_come_from_code_not_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path / "state"))
    script = """
import importlib, os
from arena.home import code_root
names = ['arena.missions_cli.common', 'arena.agentctl_extras.common']
if os.name != 'nt': names.append('arena.chat_cli.common')
for name in names:
    module = importlib.import_module(name)
    executable = getattr(module, 'AGENT', getattr(module, 'AGENTCTL', None))
    assert executable == code_root() / 'bin' / 'agentctl', (name, executable)
"""
    subprocess.run([sys.executable, "-c", script], check=True, env=os.environ.copy())


def test_audit_append_and_rotation_use_audit_parent(tmp_path):
    from arena.observability.audit import write_audit_event
    code, state = tmp_path / "code", tmp_path / "state"
    code.mkdir()
    audit = state / "audit.jsonl"
    write_audit_event({"type": "first"}, audit_path=audit, app_dir=code, utc_now_fn=lambda: "now")
    with audit.open("ab") as out:
        out.truncate(50 * 1024 * 1024)
    write_audit_event({"type": "second"}, audit_path=audit, app_dir=code, utc_now_fn=lambda: "now")
    assert (state / "audit.jsonl.1").exists()
    assert not (code / "audit.jsonl.1").exists()


def test_windows_launcher_uses_code_entry_point_and_state_home(tmp_path, monkeypatch):
    from arena.service import autostart_doctor
    state, code = tmp_path / "state", tmp_path / "code"
    state.mkdir()
    code.mkdir()
    monkeypatch.setattr(autostart_doctor, "code_root", lambda: code, raising=False)
    autostart_doctor.write_windows_launchers(state)
    body = (state / "start_bridge.bat").read_text(encoding="utf-8")
    assert f'"{code / "unified_bridge.py"}" serve' in body
    assert f"ARENA_AGENT_HOME={state}" in body


def test_mission_recording_uses_code_helper_and_state_output(tmp_path, monkeypatch):
    from arena.missions_cli import common

    home, code = tmp_path / "state", tmp_path / "code"
    monkeypatch.setenv("ARENA_REC", "1")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(home))
    monkeypatch.setattr(common, "code_root", lambda: code)
    seen = []

    class Process:
        pid = 123

    def fake_popen(cmd, **kwargs):
        seen.append(cmd)
        return Process()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    result = common._start_recording("example")
    assert result["out"] == str(home / "reports" / "recordings" / "mission-example.mp4")
    assert seen[0][0] == str(code / "bin" / "sd-exec")
