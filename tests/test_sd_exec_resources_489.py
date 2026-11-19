"""Installed sd-exec must support scope mode and systemd-less Linux hosts."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _module():
    loader = importlib.machinery.SourceFileLoader("sd_exec_resource", str(Path(__file__).resolve().parents[1] / "bin/sd-exec"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_scope_never_receives_service_only_pipe_flag(monkeypatch):
    module = _module()
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kw: (calls.append(argv) or SimpleNamespace(returncode=0)))
    opts = {"no_pipe": False, "timeout": None, "background": False}
    assert module._run_systemd(opts, ["echo", "safe"]) == 0
    assert "--scope" in calls[0]
    assert "--pipe" not in calls[0]


def test_installed_systemd_binary_without_user_bus_uses_plain_execution(monkeypatch):
    module = _module()
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    calls = []
    monkeypatch.setattr(module, "_run_plain", lambda opts, cmd: (calls.append(cmd) or 7))
    monkeypatch.setattr(module, "_run_systemd", lambda *a: (_ for _ in ()).throw(AssertionError("no user bus")))
    assert module.main(["--", "echo", "safe"]) == 7
    assert calls == [["echo", "safe"]]
