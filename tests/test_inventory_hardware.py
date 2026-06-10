"""Regression tests for inventory/hardware consolidation."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.inventory as inv  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_inventory_run_accepts_shell_kwarg():
    # Windows CIM used to call _run(..., shell=True) while _run did not accept
    # that parameter, silently breaking all CIM-backed inventory sections.
    out = inv._run("printf arena", shell=True)
    assert out == "arena"


def test_ver_filters_noisy_error_banner(monkeypatch):
    monkeypatch.setattr(inv, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(inv, "_run", lambda *a, **kw: "The command could not be loaded, possibly because:\nUsage: dotnet ...\n")
    assert inv._ver("dotnet") == "/bin/dotnet"


def test_hardware_from_inventory_normalizes_and_merges_nvidia(monkeypatch):
    fake_inventory = {
        "generated_at": "2026-06-10T00:00:00+00:00",
        "os": {"system": "Linux"},
        "cpu": {"name": "CPU", "cores_physical": 4, "cores_logical": 8, "max_ghz": 4.2},
        "memory": {"total_gb": 32, "available_gb": 20, "used_gb": 12, "modules": [{"size_gb": 16}]},
        "motherboard": {"motherboard": {"product": "Board"}, "bios": {"version": "1.0"}},
        "gpu": {
            "gpus": [{"name": "NVIDIA GPU", "vram_mb": 0}],
            "nvidia": [{"name": "NVIDIA GPU", "vram_total_mb": 4096, "temperature_c": 40}],
        },
        "disks": [{"mount": "/", "total_gb": 100}],
        "network": {"interfaces": []},
        "displays": {"screens": []},
        "runtimes": {"python": "Python 3.x"},
        "package_managers": {},
        "browsers": {},
    }

    monkeypatch.setattr(ub, "_inventory_sync", lambda section, fmt, timeout: {"ok": True, "inventory": fake_inventory, "exit_code": 0, "stderr": ""})
    res = ub._hardware_from_inventory_sync()

    assert res["ok"] is True
    hw = res["hardware"]
    assert hw["motherboard"] == {"product": "Board"}
    assert hw["bios"] == {"version": "1.0"}
    assert hw["cpu"]["cores"] == 4
    assert hw["cpu"]["threads"] == 8
    assert hw["gpu"]["vram_mb"] == 4096
    assert hw["gpu"]["temperature_c"] == 40
    assert hw["ram_total_gb"] == 32
    assert hw["ram_modules"] == [{"size_gb": 16}]


def test_hardware_from_inventory_includes_device_sections(monkeypatch):
    fake_inventory = {
        "generated_at": "2026-06-10T00:00:00+00:00",
        "os": {}, "cpu": {}, "memory": {}, "motherboard": {}, "gpu": {},
        "disks": [], "network": {}, "displays": {}, "runtimes": {}, "package_managers": {}, "browsers": {},
        "storage_devices": [{"path": "/dev/sda", "size_gb": 100}],
        "pci_devices": [{"category": "gpu", "description": "GPU"}],
        "usb_devices": [{"id": "1234:5678", "name": "USB"}],
        "thermal": {"temperatures": [{"type": "cpu", "celsius": 42.0}]},
    }
    monkeypatch.setattr(ub, "_inventory_sync", lambda section, fmt, timeout: {"ok": True, "inventory": fake_inventory, "exit_code": 0, "stderr": ""})
    hw = ub._hardware_from_inventory_sync()["hardware"]
    assert hw["devices"]["storage"] == [{"path": "/dev/sda", "size_gb": 100}]
    assert hw["devices"]["pci"][0]["category"] == "gpu"
    assert hw["devices"]["usb"][0]["name"] == "USB"
    assert hw["thermal"]["temperatures"][0]["celsius"] == 42.0


def test_normalize_third_party_skill_name_accepts_listed_name():
    assert ub._normalize_third_party_skill_name("third_party/weather") == ("weather", None)
    assert ub._normalize_third_party_skill_name("weather") == ("weather", None)
    assert ub._normalize_third_party_skill_name("skills/third_party/weather") == ("weather", None)
    assert ub._normalize_third_party_skill_name("third_party/_probe") == ("_probe", None)


def test_normalize_third_party_skill_name_rejects_core_and_traversal():
    assert ub._normalize_third_party_skill_name("core/cleanup")[1]
    assert ub._normalize_third_party_skill_name("../weather")[1]
    assert ub._normalize_third_party_skill_name("third_party/../weather")[1]
