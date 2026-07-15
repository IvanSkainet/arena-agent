"""Inventory aggregation and text formatting."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403
from arena.inventory.probe_identity import get_identity, get_os
from arena.inventory.probe_hardware import get_cpu, get_memory, get_gpu, get_motherboard
from arena.inventory.probe_devices import get_disks, get_storage_devices, get_pci_devices, get_usb_devices, get_thermal, get_network, get_displays
from arena.inventory.probe_sensors import get_battery, get_fans, get_audio, get_disk_smart, get_thermal_detail
from arena.inventory.probe_software import get_runtimes, get_package_managers, get_browsers, get_env, get_services, get_python_env

SECTIONS = [
    ("identity", get_identity),
    ("os", get_os),
    ("cpu", get_cpu),
    ("memory", get_memory),
    ("motherboard", get_motherboard),
    ("gpu", get_gpu),
    ("disks", get_disks),
    ("storage_devices", get_storage_devices),
    ("pci_devices", get_pci_devices),
    ("usb_devices", get_usb_devices),
    ("thermal", get_thermal),
    ("thermal_detail", get_thermal_detail),
    ("fans", get_fans),
    ("battery", get_battery),
    ("audio", get_audio),
    ("disk_smart", get_disk_smart),
    ("network", get_network),
    ("runtimes", get_runtimes),
    ("package_managers", get_package_managers),
    ("browsers", get_browsers),
    ("displays", get_displays),
    ("env", get_env),
    ("services", get_services),
    ("python_env", get_python_env),
]


def collect(only_section: Optional[str] = None) -> dict:
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "arena-inventory",
        "tool_version": "1.0.0",
    }
    for name, fn in SECTIONS:
        if only_section and name != only_section:
            continue
        try:
            result[name] = fn()
        except Exception as e:
            result[name] = {"error": str(e)}
    return result


from arena.inventory.text_format import format_text  # noqa: E402,F401
