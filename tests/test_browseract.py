"""BrowserAct admin regressions.

Cross-platform contract tests. Never touch the network; do not require
browser-act to be actually installed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.browseract import (
    UPSTREAM_PACKAGE,
    _cli_candidates,
    _cli_source,
    _install_hint,
    _update_hint,
    browseract_doctor,
    browseract_status,
)


@pytest.fixture(autouse=True)
def private_browseract_discovery(monkeypatch):
    """Contract defaults must not invoke the developer's installed CLI."""
    import arena.admin.browseract as mod

    monkeypatch.setattr(mod, "_cli_candidates", lambda: [])


def test_status_contract_shape():
    result = browseract_status()
    for key in ("ok", "installed", "cli_path", "cli_source", "version", "platform", "hint"):
        assert key in result


def test_status_ok_false_when_not_installed():
    """If the CLI is missing, the shape stays stable and hint is populated."""
    result = browseract_status()
    assert result["installed"] is False
    assert result["ok"] is False
    assert "uv tool install" in (result.get("hint") or "")


def test_install_hint_contains_package_name():
    assert UPSTREAM_PACKAGE in _install_hint()


def test_update_hint_uv_tool():
    assert "uv tool upgrade" in _update_hint("uv-tool")


def test_update_hint_pipx():
    assert "pipx upgrade" in _update_hint("pipx")


def test_update_hint_unknown_source_offers_reinstall():
    assert "install" in _update_hint("unknown").lower()


def test_cli_candidates_dedup_and_executable(monkeypatch, tmp_path):
    """A CLI found both on PATH and in a well-known directory is listed once.

    The home directory and the PATH lookup are private to the test, so the
    result does not depend on what is installed on the machine running it.
    """
    import os
    import platform

    import arena.admin.browseract as mod

    name = "browser-act.exe" if platform.system().lower() == "windows" else "browser-act"
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    cli = bin_dir / name
    cli.write_text("", encoding="utf-8")
    cli.chmod(0o755)

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # PATH lookup returns the very file that also sits in ~/.local/bin.
    monkeypatch.setattr(mod.shutil, "which", lambda _name: str(cli))

    found = _cli_candidates()
    assert found == [str(cli)]
    for path in found:
        assert os.path.isfile(path)
        assert os.access(path, os.X_OK)


def test_cli_source_recognises_uv_tool_path():
    """The uv/tools path family should be classified as 'uv-tool'."""
    assert _cli_source("/home/whoever/.local/share/uv/tools/browser-act-cli/bin/browser-act") == "uv-tool"


def test_cli_source_recognises_pipx():
    assert _cli_source("/home/whoever/.local/pipx/venvs/browser-act-cli/bin/browser-act") == "pipx"


def test_doctor_contract_when_not_installed():
    doc = browseract_doctor()
    assert doc["installed"] is False
    assert doc["handshake"] is False
    assert "not installed" in doc.get("error", "").lower()


def test_platform_string_is_documented_value():
    result = browseract_status()
    assert result["platform"] in ("windows", "darwin", "linux")


def test_status_forwards_host_subprocess_options(monkeypatch):
    """Windows child-window suppression must reach the version probe."""
    import arena.admin.browseract as mod

    seen = []
    monkeypatch.setattr(mod, "_cli_candidates", lambda: ["browser-act"])
    monkeypatch.setattr(mod, "_cli_source", lambda _path: "test")
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *args, **kwargs: (
            seen.append((args, kwargs))
            or SimpleNamespace(returncode=0, stdout="browser-act 2.0.2", stderr="")
        ),
    )
    options = {"creationflags": 0x1234}

    result = mod.browseract_status(subprocess_kwargs=lambda: options)

    assert result["version"] == "2.0.2"
    assert seen[0][1]["creationflags"] == 0x1234


def test_doctor_forwards_host_subprocess_options(monkeypatch):
    """The handshake must use the same Windows-safe subprocess policy."""
    import arena.admin.browseract as mod

    seen = []
    monkeypatch.setattr(mod, "_cli_candidates", lambda: ["browser-act"])
    monkeypatch.setattr(mod, "_cli_source", lambda _path: "test")
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *args, **kwargs: (
            seen.append((args, kwargs))
            or SimpleNamespace(returncode=0, stdout="ok", stderr="")
        ),
    )
    options = {"creationflags": 0x5678}

    result = mod.browseract_doctor(subprocess_kwargs=lambda: options)

    assert result["handshake"] is True
    assert [call[1]["creationflags"] for call in seen] == [0x5678, 0x5678]
