"""Unit tests for arena/inventory/probe_sensors.py.

The probes are pure best-effort and must:
  * always return a dict with an ``available`` bool key;
  * never raise;
  * degrade cleanly when the underlying tool (smartctl, pactl,
    psutil, /sys files) is missing.

These tests use monkeypatching against ``psutil`` and the module-
local ``_which`` / ``_run`` helpers so they work on any CI host
regardless of what hardware is actually present.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _import_module():
    # Reimport fresh in each test to avoid state leaking through the
    # `from probe_common import *` glob.
    if "arena.inventory.probe_sensors" in sys.modules:
        del sys.modules["arena.inventory.probe_sensors"]
    from arena.inventory import probe_sensors  # noqa: E402
    return probe_sensors


# ---------- shape & no-raise ------------------------------------------------

def test_probes_return_available_dict():
    m = _import_module()
    for fn_name in ("get_battery", "get_fans", "get_audio",
                    "get_disk_smart", "get_thermal_detail"):
        result = getattr(m, fn_name)()
        assert isinstance(result, dict), f"{fn_name} must return dict"
        assert "available" in result, f"{fn_name} must include 'available' key"
        assert isinstance(result["available"], bool)


def test_disk_smart_reports_unavailable_when_smartctl_missing():
    m = _import_module()
    with patch.object(m, "_which", return_value=None):
        result = m.get_disk_smart()
    assert result["available"] is False
    assert "smartctl" in (result.get("error") or "").lower()


# ---------- battery via psutil mock ----------------------------------------

def test_battery_uses_psutil_when_available():
    m = _import_module()
    fake_psutil = SimpleNamespace(
        sensors_battery=lambda: SimpleNamespace(
            percent=87.3, power_plugged=True, secsleft=12345
        ),
        POWER_TIME_UNLIMITED=-1,
        POWER_TIME_UNKNOWN=-2,
    )
    with patch.dict(sys.modules, {"psutil": fake_psutil}):
        result = m.get_battery()
    assert result["available"] is True
    assert result["percent"] == 87.3
    assert result["plugged"] is True
    assert result["seconds_left"] == 12345


def test_battery_handles_no_psutil():
    m = _import_module()
    # psutil import will fail
    with patch.dict(sys.modules, {"psutil": None}):
        try:
            del sys.modules["psutil"]
        except KeyError:
            pass
        result = m.get_battery()
    assert isinstance(result, dict)
    assert "available" in result


# ---------- fans via psutil mock -------------------------------------------

def test_fans_reads_psutil_sensors_fans():
    m = _import_module()
    fake_psutil = SimpleNamespace(
        sensors_fans=lambda: {
            "acpi_fan": [SimpleNamespace(label="CPU Fan", current=1420)],
        },
    )
    with patch.dict(sys.modules, {"psutil": fake_psutil}):
        result = m.get_fans()
    assert result["available"] is True
    assert result["fans"][0]["rpm"] == 1420
    assert result["fans"][0]["label"] == "CPU Fan"


def test_fans_no_backend_returns_unavailable():
    m = _import_module()
    fake_psutil = SimpleNamespace(sensors_fans=lambda: {})
    with patch.dict(sys.modules, {"psutil": fake_psutil}):
        # Force non-Windows so we don't hit WMI fallback
        with patch.object(m, "platform") as pm:
            pm.system.return_value = "Linux"
            result = m.get_fans()
    assert result["available"] is False
    assert result["fans"] == []


# ---------- audio via pactl mock -------------------------------------------

def test_audio_parses_pactl_short_output():
    m = _import_module()
    pactl_sinks = (
        "0\talsa_output.pci-0000_00_1f.3.analog-stereo\tPipeWire\ts16le 2ch 48000Hz\tRUNNING\n"
    )
    pactl_sources = ""
    call_count = {"n": 0}
    def fake_run(cmd, timeout=5.0, **kw):
        call_count["n"] += 1
        if "sinks" in cmd:
            return pactl_sinks
        return pactl_sources
    with patch.object(m, "platform") as pm:
        pm.system.return_value = "Linux"
        with patch.object(m, "_which", side_effect=lambda x: "/usr/bin/" + x if x == "pactl" else None):
            with patch.object(m, "_run", side_effect=fake_run):
                result = m.get_audio()
    assert result["available"] is True
    assert len(result["sinks"]) == 1
    assert "alsa_output" in result["sinks"][0]["name"]


# ---------- thermal_detail classification ----------------------------------

def test_thermal_detail_classifies_sensor_labels():
    m = _import_module()
    fake_psutil = SimpleNamespace(
        sensors_temperatures=lambda: {
            "coretemp": [SimpleNamespace(label="Package id 0",
                                          current=55.0, high=80.0, critical=100.0)],
            "nvme": [SimpleNamespace(label="Composite",
                                      current=42.0, high=None, critical=None)],
            "amdgpu": [SimpleNamespace(label="edge",
                                        current=48.0, high=None, critical=None)],
        }
    )
    with patch.dict(sys.modules, {"psutil": fake_psutil}):
        result = m.get_thermal_detail()
    assert result["available"] is True
    classes = {s["class"] for s in result["sensors"]}
    assert "cpu" in classes
    assert "nvme" in classes
    assert "gpu" in classes


# ---------- registry integration -------------------------------------------

def test_sections_include_new_probes():
    """The new probes must be reachable via the collect() aggregator so
    /v1/inventory can serve them."""
    from arena.inventory.report import SECTIONS
    names = [name for name, _ in SECTIONS]
    for expected in ("battery", "fans", "audio", "disk_smart", "thermal_detail"):
        assert expected in names, f"SECTIONS missing '{expected}': {names}"
