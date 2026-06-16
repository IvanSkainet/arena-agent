"""Compatibility aggregator for device/environment inventory probes."""
from __future__ import annotations

from arena.inventory.probe_buses import get_pci_devices, get_usb_devices
from arena.inventory.probe_environment import get_displays, get_network, get_thermal
from arena.inventory.probe_storage import get_disks, get_storage_devices

__all__ = [
    "get_disks", "get_storage_devices", "get_pci_devices", "get_usb_devices",
    "get_thermal", "get_network", "get_displays",
]
