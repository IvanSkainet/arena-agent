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


def test_get_active_window_prefers_kwin_querywindowinfo(monkeypatch):
    import asyncio
    import arena.desktop.active_window as aw

    async def _exec(cmd: str, timeout: float = 10):
        return {
            "ok": True,
            "stdout": "caption: Arena Window\nresourceClass: librewolf\nresourceName: librewolf\ndesktopFile: librewolf\nuuid: {abc}\nx: 10\ny: 20\nwidth: 300\nheight: 200\n",
            "stderr": "",
        }

    monkeypatch.setattr(aw.shutil, "which", lambda name: "/usr/bin/qdbus6" if name == "qdbus6" else None)
    monkeypatch.setattr(aw, "_desktop_exec", _exec)
    result = asyncio.run(aw._get_active_window())
    assert result["backend"] == "kwin_dbus"
    assert result["title"] == "Arena Window"
    assert result["class"] == "librewolf"
    assert result["geometry"] == {"x": 10, "y": 20, "width": 300, "height": 200}


def test_get_active_window_accepts_kwin_info_without_caption_or_uuid(monkeypatch):
    import asyncio
    import arena.desktop.active_window as aw

    async def _exec(cmd: str, timeout: float = 10):
        return {
            "ok": True,
            "stdout": "resourceClass: plasmashell\nresourceName: plasmashell\nx: 0\ny: 0\nwidth: 32\nheight: 32\n",
            "stderr": "",
        }

    monkeypatch.setattr(aw.shutil, "which", lambda name: "/usr/bin/qdbus6" if name == "qdbus6" else None)
    monkeypatch.setattr(aw, "_desktop_exec", _exec)
    result = asyncio.run(aw._get_active_window())
    assert result["backend"] == "kwin_dbus"
    assert result["id"] == "plasmashell"
    assert result["class"] == "plasmashell"
    assert result["geometry"] == {"x": 0, "y": 0, "width": 32, "height": 32}


def test_get_active_window_retries_kwin_before_fallback(monkeypatch):
    import asyncio
    import arena.desktop.active_window as aw

    calls = {"count": 0}

    async def _exec(cmd: str, timeout: float = 10):
        if "queryWindowInfo" in cmd:
            calls["count"] += 1
            if calls["count"] == 1:
                return {"ok": True, "stdout": "", "stderr": ""}
            return {"ok": True, "stdout": "caption: Retry Window\nresourceClass: retry\nresourceName: retry\n", "stderr": ""}
        return {"ok": False, "stdout": "", "stderr": "should not fallback"}

    monkeypatch.setattr(aw.shutil, "which", lambda name: "/usr/bin/qdbus6" if name == "qdbus6" else None)
    monkeypatch.setattr(aw, "_desktop_exec", _exec)
    result = asyncio.run(aw._get_active_window())
    assert calls["count"] == 2
    assert result["backend"] == "kwin_dbus"
    assert result["title"] == "Retry Window"


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
            return {"ok": True, "stdout": "1\n", "stderr": ""}
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
