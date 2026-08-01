"""v4.102.0 -- fail-closed code runner + code.run tool tests."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.autonomy import (
    deps as D,  # noqa: E402
    posture as P,  # noqa: E402
    runner as R,  # noqa: E402
)
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
    assert "--same-dir" in argv
    assert "--property=PrivateNetwork=yes" in argv      # network deny
    assert "--property=DynamicUser=yes" not in argv      # user manager rejects DynamicUser
    assert "--property=ProtectSystem=strict" in argv     # fs confined
    assert any(p.startswith("--property=ReadWritePaths=") for p in argv)
    assert any(p.startswith("--property=MemoryMax=") for p in argv)
    assert argv[-3] == "--" and argv[-2] == "python3"
    assert info["refused"] is False and info["sandbox_action"] == "systemd"
    e = info["enforced"]
    assert e["network"] and not e["privilege"] and e["filesystem_confined"] and e["memory"]


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
    monkeypatch.setattr(R, "_resolve_win32_runtime", lambda lang: str(runtime))
    argv, info = R.build_command("win32", _strict(), "python3", tmp_path / "c.py", tmp_path)
    assert argv is not None
    assert argv[:4] == ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    assert "-File" in argv and str(script) in argv
    assert "-ApplicationPath" in argv and str(runtime) in argv
    assert "-ScratchDir" in argv and str(tmp_path) in argv
    assert "-RuntimeGrantDir" in argv and str(runtime.parent.resolve()) in argv
    assert "-ArgumentsJson" in argv
    assert json.loads(argv[argv.index("-ArgumentsJson") + 1]) == [str(tmp_path / "c.py")]
    assert "-ExtraGrantDirsJson" not in argv
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
    monkeypatch.setattr(R, "_resolve_win32_runtime", lambda lang: None)
    argv, info = R.build_command("win32", _strict(), "python3", tmp_path / "c.py", tmp_path)
    assert argv is None and info["refused"] is True
    assert "not found" in info["note"]


def test_build_win32_appcontainer_uses_arguments_json_and_stdin(tmp_path, monkeypatch):
    script = tmp_path / "appcontainer_run.ps1"
    script.write_text("# runner", encoding="utf-8")
    runtime = tmp_path / "Python314" / "python.exe"
    runtime.parent.mkdir()
    runtime.write_text("exe", encoding="utf-8")
    stdin = tmp_path / "stdin.txt"
    stdin.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(R, "_appcontainer_script", lambda: script)
    monkeypatch.setattr(R, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(R, "_resolve_win32_runtime", lambda lang: str(runtime))
    argv, info = R.build_command("win32", _strict(), "python3", tmp_path / "c.py", tmp_path,
                                 runtime_args=["250"], stdin_path=stdin)
    assert info["refused"] is False
    assert "-ArgumentsJson" in argv
    j = json.loads(argv[argv.index("-ArgumentsJson") + 1])
    assert j == [str(tmp_path / "c.py"), "250"]
    assert "-StdinPath" in argv and str(stdin) in argv




def test_build_win32_appcontainer_accepts_extra_grant_dirs(tmp_path, monkeypatch):
    script = tmp_path / "appcontainer_run.ps1"
    script.write_text("# runner", encoding="utf-8")
    runtime = tmp_path / "Python314" / "python.exe"
    runtime.parent.mkdir()
    runtime.write_text("exe", encoding="utf-8")
    dep = tmp_path / "project" / ".deps" / "python"
    dep.mkdir(parents=True)
    monkeypatch.setattr(R, "_appcontainer_script", lambda: script)
    monkeypatch.setattr(R, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(R, "_resolve_win32_runtime", lambda lang: str(runtime))
    argv, info = R.build_command("win32", _strict(), "python3", tmp_path / "c.py", tmp_path, extra_grant_dirs=[dep])
    assert info["refused"] is False
    assert "-ExtraGrantDirsJson" in argv
    assert json.loads(argv[argv.index("-ExtraGrantDirsJson") + 1]) == [str(dep)]
    assert "project dependency cache granted read/execute" in info["note"]


def test_resolve_win32_python_skips_windowsapps_alias(monkeypatch, tmp_path):
    real = tmp_path / "Python314" / "python.exe"
    real.parent.mkdir()
    real.write_text("exe", encoding="utf-8")
    alias = r"C:\Users\Ivan\AppData\Local\Microsoft\WindowsApps\python3.exe"

    monkeypatch.setattr(R.shutil, "which", lambda name: {
        "py.exe": None,
        "py": None,
        "python3": alias,
        "python": str(real),
    }.get(name))

    assert R._resolve_win32_runtime("python3") == str(real)


def test_resolve_win32_python_uses_py_launcher_real_executable(monkeypatch, tmp_path):
    real = tmp_path / "Python314" / "python.exe"
    real.parent.mkdir()
    real.write_text("exe", encoding="utf-8")

    class _Proc:
        stdout = str(real) + "\n"

    monkeypatch.setattr(R.shutil, "which", lambda name: "C:/Windows/py.exe" if name == "py.exe" else None)
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: _Proc())

    assert R._resolve_win32_runtime("python3") == str(real)


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


def test_build_go_uses_go_run_invocation(tmp_path):
    argv, info = R.build_command("linux", _off(), "go", tmp_path / "main.go", tmp_path, runtime_args=["300"])
    assert argv[-3:] == ["run", str(tmp_path / "main.go"), "300"]
    assert info["sandbox_action"] == "off"


def test_build_win32_appcontainer_refuses_go(tmp_path, monkeypatch):
    script = tmp_path / "appcontainer_run.ps1"
    script.write_text("# runner", encoding="utf-8")
    monkeypatch.setattr(R, "_appcontainer_script", lambda: script)
    monkeypatch.setattr(R, "_powershell", lambda: "powershell.exe")
    argv, info = R.build_command("win32", {**_strict(), "runtimes": ["go"]}, "go", tmp_path / "main.go", tmp_path)
    assert argv is None
    assert info["refused"] is True
    assert "NUL" in info["note"]


def test_runtime_grant_dir_for_go_uses_go_root(tmp_path):
    exe = tmp_path / "go1.26.5" / "bin" / "go.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("exe", encoding="utf-8")
    assert R._runtime_grant_dir(str(exe)) == str(exe.parent.parent.resolve())


def test_run_code_sets_go_scratch_env(monkeypatch, tmp_path):
    seen = {}

    def _fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
        return ["fake"], {"refused": False, "sandbox_action": "off", "enforced": {"network": False}}

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    managed = tmp_path / "tools" / "go1.26.5" / "bin" / ("go.exe" if sys.platform == "win32" else "go")
    managed.parent.mkdir(parents=True)
    managed.write_text("exe", encoding="utf-8")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(R, "build_command", _fake_build)
    def fake_run(*a, **kw):
        seen.update(kw["env"])
        return _Proc()
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    res = R.run_code_sync("package main\nfunc main(){}\n", "go", {**_off(), "runtimes": ["go"]}, platform="linux")
    assert res["ok"] is True
    assert seen["GOROOT"] == str(managed.parent.parent.resolve())
    assert "go-cache" in seen["GOCACHE"]


def test_run_code_runtime_allowlist_enforced():
    res = R.run_code_sync("x", "ruby", _strict(), platform="linux")
    assert res["ok"] is False and res.get("refused") is True
    assert "runtimes" in res["error"]


def test_run_code_timeout_is_propagated_into_platform_command(monkeypatch):
    seen = {}

    def _fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
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


def test_run_code_workspace_files_entry_args_stdin_and_artifacts(monkeypatch):
    seen = {}

    def _fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
        seen["entry"] = code_path.name
        seen["args"] = runtime_args
        out = scratch_dir / "out" / "result.txt"
        out.parent.mkdir()
        out.write_text((scratch_dir / "data" / "input.txt").read_text(encoding="utf-8") + "|artifact", encoding="utf-8")
        return ["fake"], {"refused": False, "sandbox_action": "off", "enforced": {"network": False}}

    class _Proc:
        returncode = 0
        stdout = "ran"
        stderr = ""

    monkeypatch.setattr(R, "build_command", _fake_build)
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: _Proc())
    res = R.run_code_sync(
        "", "python3", _off(), platform="linux",
        files=[
            {"path": "main.py", "content": "print('x')"},
            {"path": "data/input.txt", "content": "hello"},
        ],
        entry="main.py", argv=["--flag"], stdin="input-stream",
        artifacts=["out/*.txt"],
    )
    assert res["ok"] is True
    assert seen == {"entry": "main.py", "args": ["--flag"]}
    assert set(res["workspace_files"]) == {"main.py", "data/input.txt"}
    assert res["artifacts"][0]["path"] == "out/result.txt"
    assert res["artifacts"][0]["text"] == "hello|artifact"


def test_run_code_workspace_rejects_path_traversal():
    res = R.run_code_sync("", "python3", _off(), platform="linux",
                          files=[{"path": "../x.py", "content": "x"}], entry="../x.py")
    assert res["ok"] is False
    assert res.get("refused") is True
    assert "invalid workspace" in res["error"]


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


def test_run_code_python_deps_require_network_open():
    res = R.run_code_sync("print('x')", "python3", _strict(), deps={"python": ["requests"]}, platform="linux")
    assert res["ok"] is False
    assert res.get("refused") is True
    assert "network=open" in res["error"]


def test_run_code_python_deps_install_sets_pythonpath(monkeypatch):
    seen = {"pip": None, "run_env": None}

    def fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
        return ["fake"], {"refused": False, "sandbox_action": "off", "enforced": {"network": False}}

    class _PipProc:
        returncode = 0
        stdout = "pip ok"
        stderr = ""

    class _RunProc:
        returncode = 0
        stdout = "run ok"
        stderr = ""

    def fake_run(cmd, **kw):
        if "pip" in cmd:
            seen["pip"] = cmd
            return _PipProc()
        seen["run_env"] = kw["env"]
        return _RunProc()

    monkeypatch.setattr(R, "build_command", fake_build)
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(D.subprocess, "run", fake_run)
    res = R.run_code_sync("print('x')", "python3", {**_off(), "network": "open"}, deps={"python": ["requests==2.32.3"]}, platform="linux")
    assert res["ok"] is True
    assert seen["pip"] is not None
    assert "--target" in seen["pip"]
    assert ".deps" in seen["run_env"]["PYTHONPATH"]
    assert res["deps"]["python"]["installed"] == ["requests==2.32.3"]


def test_run_code_npm_deps_require_network_open():
    res = R.run_code_sync("console.log('x')", "node", _strict(), deps={"npm": ["left-pad@1.3.0"]}, platform="linux")
    assert res["ok"] is False
    assert res.get("refused") is True
    assert "network=open" in res["error"]


def test_run_code_npm_deps_install_sets_node_path(monkeypatch):
    seen = {"npm": None, "run_env": None}

    def fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
        return ["fake"], {"refused": False, "sandbox_action": "off", "enforced": {"network": False}}

    class _NpmProc:
        returncode = 0
        stdout = "npm ok"
        stderr = ""

    class _RunProc:
        returncode = 0
        stdout = "run ok"
        stderr = ""

    def fake_run(cmd, **kw):
        if "install" in cmd and "--prefix" in cmd:
            seen["npm"] = cmd
            return _NpmProc()
        seen["run_env"] = kw["env"]
        return _RunProc()

    monkeypatch.setattr(R, "build_command", fake_build)
    monkeypatch.setattr(D, "_npm_for_deps", lambda resolve_runtime: "npm")
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(D.subprocess, "run", fake_run)
    res = R.run_code_sync("console.log('x')", "node", {**_off(), "network": "open", "runtimes": ["node"]}, deps={"npm": ["left-pad@1.3.0"]}, platform="linux")
    assert res["ok"] is True
    assert seen["npm"] is not None
    assert "--prefix" in seen["npm"]
    assert "node_modules" in seen["run_env"]["NODE_PATH"]
    assert res["deps"]["npm"]["installed"] == ["left-pad@1.3.0"]


def test_run_code_go_deps_require_network_open():
    res = R.run_code_sync("package main\nfunc main(){}\n", "go", {**_off(), "network": "deny", "runtimes": ["go"]},
                          files=[{"path": "go.mod", "content": "module x\n"}, {"path": "main.go", "content": "package main\nfunc main(){}\n"}],
                          entry="main.go", deps={"go": True}, platform="linux")
    assert res["ok"] is False
    assert res.get("refused") is True
    assert "network=open" in res["error"]


def test_run_code_go_deps_run_go_mod_download(monkeypatch, tmp_path):
    seen = {"mod": None, "run_env": None}
    managed = tmp_path / "tools" / "go1.26.5" / "bin" / ("go.exe" if sys.platform == "win32" else "go")
    managed.parent.mkdir(parents=True)
    managed.write_text("exe", encoding="utf-8")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))

    def fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
        return ["fake"], {"refused": False, "sandbox_action": "off", "enforced": {"network": False}}

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kw):
        if cmd[:3] == [str(managed), "mod", "tidy"]:
            seen["mod"] = (cmd, kw)
            return _Proc()
        seen["run_env"] = kw["env"]
        return _Proc()

    monkeypatch.setattr(R, "build_command", fake_build)
    monkeypatch.setattr(R, "_resolve_runtime", lambda name: str(managed) if name == "go" else None)
    monkeypatch.setattr(D, "_npm_for_deps", lambda resolve_runtime: "npm")
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(D.subprocess, "run", fake_run)
    res = R.run_code_sync("", "go", {**_off(), "network": "open", "runtimes": ["go"]},
                          files=[{"path": "go.mod", "content": "module x\n"}, {"path": "main.go", "content": "package main\nfunc main(){}\n"}],
                          entry="main.go", deps={"go": True}, platform="linux")
    assert res["ok"] is True
    assert seen["mod"] is not None
    assert seen["mod"][1]["cwd"]
    assert "GOMODCACHE" in seen["run_env"]
    assert res["deps"]["go"]["enabled"] is True


def test_run_code_subprocess_uses_scratch_cwd(monkeypatch):
    seen = {}
    def fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
        seen["scratch"] = scratch_dir
        return ["fake"], {"refused": False, "sandbox_action": "off", "enforced": {"network": False}}
    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""
    def fake_run(*a, **kw):
        seen["cwd"] = kw.get("cwd")
        return _Proc()
    monkeypatch.setattr(R, "build_command", fake_build)
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    res = R.run_code_sync("print('x')", "python3", _off(), platform="linux")
    assert res["ok"] is True
    assert seen["cwd"] == str(seen["scratch"])


def test_build_win32_off_python_uses_real_python(monkeypatch, tmp_path):
    real = tmp_path / "Python314" / "python.exe"
    real.parent.mkdir(parents=True)
    real.write_text("exe", encoding="utf-8")
    monkeypatch.setattr(R, "_resolve_win32_runtime", lambda lang: str(real))
    argv, info = R.build_command("win32", _off(), "python3", tmp_path / "main.py", tmp_path)
    assert argv[0] == str(real)
    assert info["sandbox_action"] == "off"


def test_build_wasm_uses_wasmtime_dir_invocation(tmp_path, monkeypatch):
    wasm = tmp_path / "main.wasm"
    wasm.write_bytes(b"\0asm")
    monkeypatch.setattr(R, "_resolve_runtime", lambda lang: "/bin/wasmtime" if lang == "wasm" else None)
    argv, info = R.build_command("linux", _off(), "wasm", wasm, tmp_path, runtime_args=["a"])
    assert info["sandbox_action"] == "off"
    assert argv == ["wasmtime", "-C", "cache=n", "--dir", str(tmp_path), str(wasm), "a"]



def test_run_code_wasm_sets_scratch_home(monkeypatch):
    seen = {}

    def _fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
        seen["scratch"] = str(scratch_dir)
        return ["fake"], {"refused": False, "sandbox_action": "appcontainer", "enforced": {"network": True}}

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(R, "build_command", _fake_build)
    def fake_run(*a, **kw):
        seen.update(kw["env"])
        return _Proc()
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    res = R.run_code_sync("", "wasm", {**_strict(), "runtimes": ["wasm"]}, platform="win32", files=[{"path": "m.wasm", "content": "AGFzbQEAAAA=", "encoding": "base64"}], entry="m.wasm")
    assert res["ok"] is True
    assert seen["WASMTIME_HOME"].endswith(".wasmtime")
    assert seen["HOME"] == seen["scratch"]
    assert seen["USERPROFILE"] == seen["scratch"]


def test_build_deno_uses_permission_limited_invocation(tmp_path, monkeypatch):
    script = tmp_path / "main.ts"
    script.write_text("console.log('x')", encoding="utf-8")
    argv, info = R.build_command("linux", _off(), "deno", script, tmp_path, runtime_args=["a"])
    assert info["sandbox_action"] == "off"
    assert argv[0] == "deno"
    assert argv[1:4] == ["run", "--no-prompt", "--allow-read"]
    assert "--allow-write" in argv
    assert "--deny-net" in argv
    assert argv[-2:] == [str(script), "a"]


def test_run_code_deno_sets_scratch_home(monkeypatch):
    seen = {}
    def _fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
        seen["scratch"] = str(scratch_dir)
        return ["fake"], {"refused": False, "sandbox_action": "appcontainer", "enforced": {"network": True}}
    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""
    monkeypatch.setattr(R, "build_command", _fake_build)
    def fake_run(*a, **kw):
        seen.update(kw["env"])
        return _Proc()
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    res = R.run_code_sync("console.log('x')", "deno", {**_strict(), "runtimes": ["deno"]}, platform="win32")
    assert res["ok"] is True
    assert seen["DENO_DIR"].endswith(".deno")
    assert seen["HOME"] == seen["scratch"]


def test_build_zig_uses_scratch_cache_dirs(tmp_path):
    src = tmp_path / "main.zig"
    src.write_text("pub fn main() void {}", encoding="utf-8")
    argv, info = R.build_command("linux", _off(), "zig", src, tmp_path, runtime_args=["a"])
    assert info["sandbox_action"] == "off"
    assert argv[:3] == ["zig", "run", str(src)]
    assert "--cache-dir" in argv and str(tmp_path / ".zig-cache") in argv
    assert "--global-cache-dir" in argv and str(tmp_path / ".zig-global-cache") in argv
    assert argv[-2:] == ["--", "a"]


def test_run_code_zig_sets_cache_env(monkeypatch):
    seen = {}
    def _fake_build(platform, posture, lang, code_path, scratch_dir, runtime_args=None, stdin_path=None, extra_grant_dirs=None):
        seen["scratch"] = str(scratch_dir)
        return ["fake"], {"refused": False, "sandbox_action": "appcontainer", "enforced": {"network": True}}
    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""
    monkeypatch.setattr(R, "build_command", _fake_build)
    def fake_run(*a, **kw):
        seen.update(kw["env"])
        return _Proc()
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    res = R.run_code_sync("pub fn main() void {}", "zig", {**_strict(), "runtimes": ["zig"]}, platform="win32")
    assert res["ok"] is True
    assert seen["ZIG_LOCAL_CACHE_DIR"].endswith(".zig-cache")
    assert seen["ZIG_GLOBAL_CACHE_DIR"].endswith(".zig-global-cache")


def test_build_lua_invocation(tmp_path):
    src = tmp_path / "main.lua"
    src.write_text("print('x')", encoding="utf-8")
    argv, info = R.build_command("linux", _off(), "lua", src, tmp_path, runtime_args=["a"])
    assert info["sandbox_action"] == "off"
    assert argv == ["lua", str(src), "a"]
