"""Desktop runtime helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.desktop.runtime as dr  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_desktop_helpers_reexported():
    assert ub._desktop_exec is dr._desktop_exec
    assert ub._detect_desktop_env is dr._detect_desktop_env
    assert ub._kwin_windows_via_script is dr._kwin_windows_via_script
    assert ub._get_active_window is dr._get_active_window


def test_detect_desktop_env_shape():
    env = dr._detect_desktop_env()
    for key in ["session_type", "desktop", "desktop_session", "wayland", "x11", "has_xdotool", "has_spectacle"]:
        assert key in env


def test_get_active_window_prefers_kwin_window_list(monkeypatch):
    import asyncio
    import arena.desktop.active_window as aw

    async def _kwin_list():
        return {
            "ok": True,
            "windows": [
                {"id": "{active}", "internal_id": "{active}", "title": "Arena Window", "pid": 123, "resource_class": "librewolf", "resource_name": "librewolf", "desktop_file": "librewolf", "geometry": {"x": 10, "y": 20, "width": 300, "height": 200}, "active": True},
                {"id": "{other}", "internal_id": "{other}", "title": "Other", "active": False},
            ],
        }

    monkeypatch.setattr(aw, "_kwin_windows_via_script", _kwin_list)
    result = asyncio.run(aw._get_active_window())
    assert result["backend"] == "kwin_journal"
    assert result["title"] == "Arena Window"
    assert result["class"] == "librewolf"
    assert result["geometry"] == {"x": 10, "y": 20, "width": 300, "height": 200}


def test_get_active_window_uses_kwin_window_list_minimal_shape(monkeypatch):
    import asyncio
    import arena.desktop.active_window as aw

    async def _kwin_list():
        return {
            "ok": True,
            "windows": [
                {"id": "plasmashell-id", "internal_id": "plasmashell-id", "title": "", "pid": 55, "resource_class": "plasmashell", "resource_name": "plasmashell", "desktop_file": "", "geometry": {"x": 0, "y": 0, "width": 32, "height": 32}, "active": True},
            ],
        }

    monkeypatch.setattr(aw, "_kwin_windows_via_script", _kwin_list)
    result = asyncio.run(aw._get_active_window())
    assert result["backend"] == "kwin_journal"
    assert result["id"] == "plasmashell-id"
    assert result["class"] == "plasmashell"
    assert result["geometry"] == {"x": 0, "y": 0, "width": 32, "height": 32}


def test_get_active_window_falls_back_to_xdotool_when_kwin_list_fails(monkeypatch):
    import asyncio
    import arena.desktop.active_window as aw

    async def _kwin_list():
        return {"ok": False}

    async def _exec(cmd: str, timeout: float = 10):
        if "getactivewindow" in cmd:
            return {"ok": True, "stdout": "123\n", "stderr": ""}
        if "getwindowname" in cmd:
            return {"ok": True, "stdout": "Fallback Window\n", "stderr": ""}
        if "getwindowpid" in cmd:
            return {"ok": True, "stdout": "456\n", "stderr": ""}
        if "getwindowclassname" in cmd:
            return {"ok": True, "stdout": "fallback\n", "stderr": ""}
        if "getwindowgeometry" in cmd:
            return {"ok": True, "stdout": "Window 123\n  Position: 1,2 (screen: 0)\n  Geometry: 3x4\n", "stderr": ""}
        return {"ok": False, "stdout": "", "stderr": "unexpected"}

    monkeypatch.setattr(aw, "_kwin_windows_via_script", _kwin_list)
    monkeypatch.setattr(aw.shutil, "which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None)
    monkeypatch.setattr(aw, "_desktop_exec", _exec)
    result = asyncio.run(aw._get_active_window())
    assert result["backend"] == "xdotool"
    assert result["id"] == "123"
    assert result["title"] == "Fallback Window"


def test_kwin_windows_via_script_probes_kwin_without_desktop_env(monkeypatch):
    import asyncio
    import arena.desktop.kwin as kw

    monkeypatch.setattr(kw.shutil, "which", lambda name: "/usr/bin/" + name if name in {"qdbus6", "journalctl"} else None)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "")
    monkeypatch.setenv("XDG_SESSION_TYPE", "")

    calls = {"probe": 0, "unload": 0}

    async def _exec(cmd: str, timeout: float = 10):
        if "activeOutputName" in cmd:
            calls["probe"] += 1
            return {"ok": True, "stdout": "DP-1\n", "stderr": ""}
        if "unloadScript" in cmd:
            calls["unload"] += 1
            return {"ok": True, "stdout": "", "stderr": ""}
        if "loadScript" in cmd:
            return {"ok": True, "stdout": "0\n", "stderr": ""}
        if "org.kde.kwin.Scripting.start" in cmd:
            return {"ok": True, "stdout": "", "stderr": ""}
        if "journalctl" in cmd:
            return {"ok": True, "stdout": 'ARENA_KWIN_WINDOWS_token {"ok": true, "backend": "kwin_journal", "count": 1, "windows": [{"title": "Arena"}]}\n', "stderr": ""}
        return {"ok": False, "stdout": "", "stderr": "unexpected"}

    monkeypatch.setattr(kw, "_desktop_exec", _exec)
    monkeypatch.setattr(kw.uuid, "uuid4", lambda: type("U", (), {"hex": "token"})())
    result = asyncio.run(kw._kwin_windows_via_script())
    assert calls["probe"] == 1
    assert calls["unload"] == 1
    assert result["ok"] is True
    assert result["count"] == 1
