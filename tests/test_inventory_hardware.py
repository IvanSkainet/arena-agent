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
