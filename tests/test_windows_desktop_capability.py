"""T60: capability map must reflect the native Win32 backend handlers use."""
from __future__ import annotations

from arena.capabilities import build_capabilities
from arena.desktop.capability import windows_desktop_capability


def test_native_win32_flags_make_every_live_surface_available() -> None:
    result = windows_desktop_capability({
        "has_win32_windows": True,
        "has_win32_screenshot": True,
        "has_win32_input": True,
    })
    assert result == {
        "available": True,
        "windows": {"available": True, "backend": "native-win32"},
        "active_window": {"available": True, "backend": "native-win32"},
        "screenshot": {"available": True, "backend": "native-win32"},
        "input": {"available": True, "backend": "native-win32"},
    }


def test_partial_and_absent_backends_are_reported_independently() -> None:
    partial = windows_desktop_capability({"has_win32_windows": True})
    assert partial["available"] is True
    assert partial["windows"] == {"available": True, "backend": "native-win32"}
    assert partial["active_window"] == {"available": True, "backend": "native-win32"}
    for name in ("screenshot", "input"):
        assert partial[name] == {
            "available": False,
            "backend": "pending-win32",
            "reason": "native Windows backend was not detected",
        }

    absent = windows_desktop_capability({})
    assert absent == {
        "available": False,
        "windows": {
            "available": False, "backend": "pending-win32",
            "reason": "native Windows backend was not detected",
        },
        "active_window": {
            "available": False, "backend": "pending-win32",
            "reason": "native Windows backend was not detected",
        },
        "screenshot": {
            "available": False, "backend": "pending-win32",
            "reason": "native Windows backend was not detected",
        },
        "input": {
            "available": False, "backend": "pending-win32",
            "reason": "native Windows backend was not detected",
        },
    }


def test_build_capabilities_uses_live_win32_flags(monkeypatch) -> None:
    monkeypatch.setattr("arena.capabilities.sys.platform", "win32")
    caps = build_capabilities(
        version="test",
        cdp_module_available=False,
        cdp_connected=False,
        desktop_env={
            "session_type": "windows",
            "desktop": "Windows",
            "has_win32_windows": True,
            "has_win32_screenshot": True,
            "has_win32_input": True,
        },
        service_info_fn=lambda: {"ok": True},
        sys_svc_fn=lambda: {"tailscale": {}},
    )
    assert caps["desktop"]["available"] is True
    assert caps["desktop"]["windows"]["backend"] == "native-win32"
    assert caps["desktop"]["screenshot"]["available"] is True
    assert caps["desktop"]["input"]["available"] is True
    assert not any("desktop backend" in warning for warning in caps["warnings"])
