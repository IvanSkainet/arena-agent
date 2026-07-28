"""v4.102.0 -- fail-closed code runner + code.run tool tests."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.autonomy import posture as P  # noqa: E402
from arena.autonomy import runner as R  # noqa: E402
from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_code import handle_code_tool  # noqa: E402


def _strict():
    return {**P.PRESETS["strict"], "runtimes": ["python3", "python", "node"],
            "resources": dict(P.DEFAULT_RESOURCES)}


def _off():
    return {**_strict(), "sandbox": "off", "runtime": "any"}


# ---------------------------------------------------------------------------
# build_command / resolve -- pure, per-platform, fail-closed
# ---------------------------------------------------------------------------

def test_build_linux_systemd_strict_argv(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_have", lambda c: c == "systemd-run")
    argv, info = R.build_command("linux", _strict(), "python3",
                                 tmp_path / "c.py", tmp_path)
    assert argv[0] == "systemd-run"
    assert "--property=PrivateNetwork=yes" in argv      # network deny
    assert "--property=DynamicUser=yes" in argv          # privilege drop
    assert "--property=ProtectSystem=strict" in argv     # fs confined
    assert any(p.startswith("--property=ReadWritePaths=") for p in argv)
    assert any(p.startswith("--property=MemoryMax=") for p in argv)
    assert argv[-3] == "--" and argv[-2] == "python3"
    assert info["refused"] is False and info["sandbox_action"] == "systemd"
    e = info["enforced"]
    assert e["network"] and e["privilege"] and e["filesystem_confined"] and e["memory"]


def test_build_linux_network_open_drops_privatenetwork(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_have", lambda c: True)
    p = {**_strict(), "network": "open"}
    argv, info = R.build_command("linux", p, "python3", tmp_path / "c.py", tmp_path)
    assert "--property=PrivateNetwork=yes" not in argv
    assert info["enforced"]["network"] is False


def test_build_off_is_unfenced(tmp_path):
    argv, info = R.build_command("linux", _off(), "python3", tmp_path / "c.py", tmp_path)
    assert argv == ["python3", str(tmp_path / "c.py")]
    assert info["sandbox_action"] == "off"
    assert info["enforced"]["network"] is False and info["enforced"]["memory"] is False


def test_build_win32_appcontainer_argv(tmp_path, monkeypatch):
    script = tmp_path / "appcontainer_run.ps1"
    script.write_text("# runner", encoding="utf-8")
    runtime = tmp_path / "Python314" / "python.exe"
    runtime.parent.mkdir()
    runtime.write_text("exe", encoding="utf-8")
    monkeypatch.setattr(R, "_appcontainer_script", lambda: script)
    monkeypatch.setattr(R, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(R, "_resolve_runtime", lambda lang: str(runtime))
    argv, info = R.build_command("win32", _strict(), "python3", tmp_path / "c.py", tmp_path)
    assert argv is not None
    assert argv[:4] == ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    assert "-File" in argv and str(script) in argv
    assert "-ApplicationPath" in argv and str(runtime) in argv
    assert "-ScratchDir" in argv and str(tmp_path) in argv
    assert "-RuntimeGrantDir" in argv and str(runtime.parent.resolve()) in argv
    assert "-Arguments" in argv and str(tmp_path / "c.py") in argv
    assert info["refused"] is False and info["sandbox_action"] == "appcontainer"
    assert info["enforced"]["network"] is True
    assert info["enforced"]["privilege"] is True
    assert info["enforced"]["filesystem_confined"] is True
    assert info["enforced"]["memory"] is False


def test_build_win32_missing_runner_refused_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_appcontainer_script", lambda: tmp_path / "missing.ps1")
    monkeypatch.setattr(R, "_powershell", lambda: "powershell.exe")
    argv, info = R.build_command("win32", _strict(), "python3", tmp_path / "c.py", tmp_path)
    assert argv is None and info["refused"] is True
    assert "missing" in info["note"]


def test_build_win32_missing_runtime_refused_fail_closed(tmp_path, monkeypatch):
    script = tmp_path / "appcontainer_run.ps1"
    script.write_text("# runner", encoding="utf-8")
    monkeypatch.setattr(R, "_appcontainer_script", lambda: script)
    monkeypatch.setattr(R, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(R, "_resolve_runtime", lambda lang: None)
    argv, info = R.build_command("win32", _strict(), "python3", tmp_path / "c.py", tmp_path)
    assert argv is None and info["refused"] is True
    assert "not found" in info["note"]


def test_build_linux_microvm_refused(tmp_path):
    argv, info = R.build_command("linux", {**_strict(), "sandbox": "microvm"},
                                 "python3", tmp_path / "c.py", tmp_path)
    assert argv is None and info["refused"] is True


def test_build_linux_no_systemd_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_have", lambda c: False)
    argv, info = R.build_command("linux", _strict(), "python3", tmp_path / "c.py", tmp_path)
    assert argv is None and info["refused"] is True
    assert "systemd-run" in info["note"]


# ---------------------------------------------------------------------------
# run_code_sync -- off path actually executes (harmless); allowlist enforced
# ---------------------------------------------------------------------------

def test_run_code_off_executes_harmless():
    lang = "python3" if shutil.which("python3") else ("python" if shutil.which("python") else None)
    if lang is None:
        pytest.skip("no python interpreter available")
    res = R.run_code_sync("print('arena-ok')", lang, _off(), timeout=20,
                          platform=sys.platform)
    assert res["ok"] is True, res
    assert "arena-ok" in res["stdout"]
    assert res["enforced"]["network"] is False


def test_run_code_runtime_allowlist_enforced():
    res = R.run_code_sync("x", "ruby", _strict(), platform="linux")
    assert res["ok"] is False and res.get("refused") is True
    assert "runtimes" in res["error"]


def test_run_code_timeout_is_propagated_into_platform_command(monkeypatch):
    seen = {}

    def _fake_build(platform, posture, lang, code_path, scratch_dir):
        seen["wall"] = posture["resources"]["wall_seconds"]
        return ["fake"], {"refused": False, "sandbox_action": "appcontainer",
                          "enforced": {"network": True}}

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(R, "build_command", _fake_build)
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: _Proc())
    res = R.run_code_sync("print('x')", "python3", _strict(), timeout=7, platform="win32")
    assert res["ok"] is True
    assert seen["wall"] == 7


# ---------------------------------------------------------------------------
# code.run tool: invariant + classification
# ---------------------------------------------------------------------------

def test_code_run_rejects_posture_override_from_agent():
    out = handle_code_tool("code.run", {"code": "x", "sandbox": "off"}, ctx=object())
    assert out["isError"] is True and "operator-owned" in out["content"][0]["text"]


def test_code_run_unknown_name_falls_through():
    assert handle_code_tool("exec.exec", {"code": "x"}, ctx=object()) is None


def test_code_run_classified_dangerous():
    assert classify_tool_risk("code.run") == "dangerous"
