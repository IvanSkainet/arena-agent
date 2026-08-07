"""`/v1/capabilities` must describe reality, not a brochure.

Before v4.167.0 the mobile section reported `"backend": "adb"` as a
literal constant and returned all 51 endpoint names **regardless of
whether adb existed**. An agent reading that map would plan a screenshot
on a host with no adb and no phone, and only discover the truth from a
404 at execution time.

That is the same defect class as bug #65's decorative allow-list: a
control surface that describes itself rather than the system. The gate
here is that unavailable means empty.
"""
from __future__ import annotations

import json

import pytest

from arena import hostplatform as hp
from arena.capabilities import _MOBILE_ENDPOINTS, build_capabilities

BASE = {
    "version": "4.167.0",
    "cdp_module_available": False,
    "cdp_connected": False,
    "desktop_env": None,
    "service_info_fn": lambda: {},
    "sys_svc_fn": lambda: {},
}


def _caps(mobile_status, monkeypatch=None, android=False):
    if monkeypatch is not None:
        monkeypatch.setattr(hp, "is_android", lambda *a, **k: android)
        import arena.capabilities as capmod
        monkeypatch.setattr(capmod._host_platform, "is_android",
                            lambda *a, **k: android)
    return build_capabilities(mobile_status_fn=lambda: mobile_status, **BASE)


def test_no_adb_means_no_advertised_endpoints(monkeypatch):
    """The bug: 51 endpoints offered by a host that can serve none."""
    caps = _caps({"adb_installed": False, "devices": []}, monkeypatch,
                 android=False)
    mobile = caps["mobile"]

    assert mobile["available"] is False
    assert mobile["backend"] == "none", "backend was a hardcoded literal"
    assert mobile["endpoints"] == [], (
        f"advertised {len(mobile['endpoints'])} endpoints on a host with "
        f"no adb and no device")
    assert mobile["endpoints_unavailable_reason"], (
        "refusing without saying why is its own kind of unhelpful")


def test_adb_present_advertises_the_real_endpoint_list(monkeypatch):
    """Reverse sabotage: honesty must not become silence.

    A gate that empties the list unconditionally would 'fix' the bug by
    breaking every working desktop.
    """
    caps = _caps({"adb_installed": True, "adb_path": "/usr/bin/adb",
                  "adb_version": "1.0.41",
                  "devices": [{"serial": "2200ad3b"}]}, monkeypatch,
                 android=False)
    mobile = caps["mobile"]

    assert mobile["available"] is True
    assert mobile["backend"] == "adb"
    assert list(mobile["endpoints"]) == list(_MOBILE_ENDPOINTS)
    assert mobile["devices"] == 1
    assert mobile["device_serials"] == ["2200ad3b"]
    assert mobile["endpoints_unavailable_reason"] is None


def test_on_device_reports_the_on_device_backend(monkeypatch):
    """Running ON the phone: no adb, yet mobile is very much available.

    This is the case the hardcoded `"adb"` made unrepresentable. A phone
    running the bridge in Termux has no adb binary and does not need
    one -- reporting `available: false` there would be exactly as wrong
    as the original bug, in the other direction.
    """
    caps = _caps({"adb_installed": False, "devices": []}, monkeypatch,
                 android=True)
    mobile = caps["mobile"]

    assert mobile["available"] is True, "the bridge IS the phone"
    assert mobile["backend"] == "on-device"
    assert list(mobile["endpoints"]) == list(_MOBILE_ENDPOINTS)


def test_the_platform_block_exposes_a_host_class():
    """`system: linux` is true on a phone and useless.

    Agents need something they can branch on without re-deriving the
    Android test themselves.
    """
    caps = build_capabilities(mobile_status_fn=None, **BASE)
    platform_block = caps["platform"]

    assert "class" in platform_block
    assert platform_block["class"] in {
        hp.WINDOWS, hp.MACOS, hp.ANDROID, hp.LINUX, hp.UNKNOWN}
    assert "systemd" in platform_block
    assert "termux" in platform_block


def test_a_failing_mobile_probe_still_reports_honestly():
    """An exception must not resurrect the brochure."""
    def explode():
        raise RuntimeError("adb probe blew up")

    caps = build_capabilities(mobile_status_fn=explode, **BASE)
    mobile = caps["mobile"]

    assert mobile["available"] is False
    assert mobile["backend"] == "none"
    assert mobile["endpoints"] == []
    assert "blew up" in mobile["error"]


def test_capabilities_remain_json_serialisable():
    caps = build_capabilities(
        mobile_status_fn=lambda: {"adb_installed": True, "devices": []},
        **BASE)
    json.dumps(caps)


@pytest.mark.parametrize("advertised", [_MOBILE_ENDPOINTS])
def test_the_endpoint_table_is_not_empty(advertised):
    """Guards the guard: an empty table would make every test above pass."""
    assert len(advertised) > 40
