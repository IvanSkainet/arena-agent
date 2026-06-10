"""Hardware normalization module tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.inventory.hardware import hardware_from_inventory_result, normalize_inventory_hardware  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_normalize_inventory_hardware_merges_nvidia_and_devices():
    inv = {
        "generated_at": "now",
        "cpu": {"name": "CPU", "cores_physical": 4, "cores_logical": 8},
        "memory": {"total_gb": 32, "modules": [{"size_gb": 16}]},
        "motherboard": {"motherboard": {"product": "Board"}, "bios": {"version": "1"}},
        "gpu": {"gpus": [{"name": "GPU", "vram_mb": 0}], "nvidia": [{"vram_total_mb": 4096, "temperature_c": 40}]},
        "storage_devices": [{"path": "/dev/sda"}],
        "pci_devices": [{"category": "storage"}],
        "usb_devices": [{"name": "usb"}],
        "thermal": {"temperatures": [{"celsius": 42}]},
    }
    hw = normalize_inventory_hardware(inv)
    assert hw["gpu"]["vram_mb"] == 4096
    assert hw["gpu"]["temperature_c"] == 40
    assert hw["devices"]["storage"] == [{"path": "/dev/sda"}]
    assert hw["devices"]["pci"] == [{"category": "storage"}]
    assert hw["thermal"]["temperatures"][0]["celsius"] == 42
    assert hw["ram_total_gb"] == 32
    assert hw["ram_modules"] == [{"size_gb": 16}]


def test_hardware_from_inventory_result_fallback():
    res = hardware_from_inventory_result({"ok": False, "error": "boom"}, legacy_hwinfo_fn=lambda: {"legacy": True})
    assert res["ok"] is True
    assert res["source"] == "legacy_hwinfo_fallback"
    assert res["hardware"] == {"legacy": True}


def test_unified_bridge_reexports_hardware_helpers():
    assert ub.normalize_inventory_hardware is normalize_inventory_hardware
