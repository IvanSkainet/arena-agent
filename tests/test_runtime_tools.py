"""v4.108.0 -- managed runtime probe/install MCP tools."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_runtime import handle_runtime_tool  # noqa: E402
from arena.workbench import runtimes  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_runtime_tools_registered():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"runtime.probe", "runtime.list", "runtime.install"} <= names


def test_runtime_policy_classification():
    assert classify_tool_risk("runtime.probe") == "safe"
    assert classify_tool_risk("runtime.list") == "safe"
    assert classify_tool_risk("runtime.install") == "medium"


def test_runtime_probe_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(runtimes, "_which", lambda name: "/bin/" + name if name in {"python3", "node"} else None)
    monkeypatch.setattr(runtimes, "_run_version", lambda exe, args=None: f"{Path(exe).name} 1.2.3")
    out = runtimes.probe()
    assert out["ok"] is True
    assert out["runtimes"]["python3"]["available"] is True
    assert out["runtimes"]["node"]["version"] == "node 1.2.3"
    assert "managed_home" in out


def test_runtime_install_unsupported():
    out = _parsed(handle_runtime_tool("runtime.install", {"runtime": "ruby"}, ctx=object()))
    assert out["ok"] is False
    assert "supports" in out["error"]


def test_runtime_probe_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(runtimes, "probe", lambda: {"ok": True, "runtimes": {"go": {"available": False}}})
    out = _parsed(handle_runtime_tool("runtime.probe", {}, ctx=object()))
    assert out == {"ok": True, "runtimes": {"go": {"available": False}}}


def test_runner_resolves_managed_go(monkeypatch, tmp_path):
    from arena.autonomy import runner as R
    managed = tmp_path / "tools" / "go1.2.3" / "bin" / ("go.exe" if sys.platform == "win32" else "go")
    managed.parent.mkdir(parents=True)
    managed.write_text("exe", encoding="utf-8")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(R.shutil, "which", lambda name: None)
    assert R._resolve_runtime("go") == str(managed)


def test_runtime_probe_resolves_managed_wasmtime(monkeypatch, tmp_path):
    exe = tmp_path / "tools" / "wasmtime-47.0.2" / ("wasmtime.exe" if sys.platform == "win32" else "wasmtime")
    exe.parent.mkdir(parents=True)
    exe.write_text("exe", encoding="utf-8")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(runtimes, "_which", lambda name: None)
    monkeypatch.setattr(runtimes, "_run_version", lambda exe, args=None: "wasmtime 47.0.2")
    out = runtimes.probe()
    assert out["runtimes"]["wasmtime"]["available"] is True
    assert out["runtimes"]["wasm"]["managed"] is True


def test_runtime_install_supports_wasmtime(monkeypatch):
    monkeypatch.setattr(runtimes, "install_wasmtime", lambda version=None: {"ok": True, "runtime": "wasmtime", "version": version or "latest"})
    out = _parsed(handle_runtime_tool("runtime.install", {"runtime": "wasmtime"}, ctx=object()))
    assert out == {"ok": True, "runtime": "wasmtime", "version": "latest"}


def test_runtime_probe_resolves_managed_deno(monkeypatch, tmp_path):
    exe = tmp_path / "tools" / "deno-2.9.4" / ("deno.exe" if sys.platform == "win32" else "deno")
    exe.parent.mkdir(parents=True)
    exe.write_text("exe", encoding="utf-8")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(runtimes, "_which", lambda name: None)
    monkeypatch.setattr(runtimes, "_run_version", lambda exe, args=None: "deno 2.9.4")
    out = runtimes.probe()
    assert out["runtimes"]["deno"]["available"] is True
    assert out["runtimes"]["deno"]["managed"] is True


def test_runtime_install_supports_deno(monkeypatch):
    monkeypatch.setattr(runtimes, "install_deno", lambda version=None, sha256=None: {"ok": True, "runtime": "deno", "version": version or "latest", "sha256": sha256})
    out = _parsed(handle_runtime_tool("runtime.install", {"runtime": "deno"}, ctx=object()))
    assert out == {"ok": True, "runtime": "deno", "version": "latest", "sha256": None}


def test_runtime_probe_resolves_managed_zig(monkeypatch, tmp_path):
    exe = tmp_path / "tools" / "zig-0.16.0" / ("zig.exe" if sys.platform == "win32" else "zig")
    exe.parent.mkdir(parents=True)
    exe.write_text("exe", encoding="utf-8")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(runtimes, "_which", lambda name: None)
    monkeypatch.setattr(runtimes, "_run_version", lambda exe, args=None: "0.16.0")
    out = runtimes.probe()
    assert out["runtimes"]["zig"]["available"] is True
    assert out["runtimes"]["zig"]["managed"] is True


def test_runtime_install_supports_zig(monkeypatch):
    monkeypatch.setattr(runtimes, "install_zig", lambda version=None: {"ok": True, "runtime": "zig", "version": version or "latest"})
    out = _parsed(handle_runtime_tool("runtime.install", {"runtime": "zig"}, ctx=object()))
    assert out == {"ok": True, "runtime": "zig", "version": "latest"}
