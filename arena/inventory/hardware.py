"""Hardware inventory normalization helpers.

This module converts the rich but broad `scripts/inventory.py --json` payload
into the stable `/v1/hardware` API shape. It is intentionally pure and does not
run subprocesses; the caller is responsible for collecting inventory data.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def merge_nvidia_gpu_facts(gpu_section: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge generic GPU facts with richer NVIDIA-SMI telemetry."""
    gpus = list(gpu_section.get("gpus") or [])
    nvidia_cards = gpu_section.get("nvidia") or []
    for idx, card in enumerate(nvidia_cards):
        if idx < len(gpus):
            gpus[idx].update({k: v for k, v in card.items() if v not in (None, "")})
            if "vram_total_mb" in card and not gpus[idx].get("vram_mb"):
                gpus[idx]["vram_mb"] = card.get("vram_total_mb")
        else:
            gpus.append(dict(card))
    return gpus


def normalize_inventory_hardware(inv: dict[str, Any]) -> dict[str, Any]:
    """Normalize a full inventory.py JSON payload into `/v1/hardware` shape."""
    mb = inv.get("motherboard") or {}
    memory = inv.get("memory") or {}
    gpu = inv.get("gpu") or {}
    gpus = merge_nvidia_gpu_facts(gpu)
    cpu = inv.get("cpu") or {}

    hardware = {
        "generated_at": inv.get("generated_at"),
        "os": inv.get("os") or {},
        "cpu": {
            "name": cpu.get("name") or cpu.get("processor"),
            "manufacturer": cpu.get("manufacturer"),
            "cores": cpu.get("cores_physical"),
            "threads": cpu.get("cores_logical"),
            "current_ghz": cpu.get("current_ghz"),
            "max_ghz": cpu.get("max_ghz"),
            "load_avg": cpu.get("load_avg"),
            "raw": cpu,
        },
        "memory": memory,
        "motherboard": mb.get("motherboard"),
        "bios": mb.get("bios"),
        "gpu": gpus[0] if gpus else None,
        "gpus": gpus,
        "disks": inv.get("disks") or [],
        "devices": {
            "storage": inv.get("storage_devices") or [],
            "pci": inv.get("pci_devices") or [],
            "usb": inv.get("usb_devices") or [],
        },
        "thermal": inv.get("thermal") or {},
        "network": inv.get("network") or {},
        "displays": inv.get("displays") or {},
        "runtimes": inv.get("runtimes") or {},
        "package_managers": inv.get("package_managers") or {},
        "browsers": inv.get("browsers") or {},
    }

    # Legacy aliases expected by older dashboard/cards.
    hardware["ram_total_gb"] = memory.get("total_gb")
    hardware["ram_used_gb"] = memory.get("used_gb")
    hardware["ram_avail_gb"] = memory.get("available_gb")
    hardware["ram_modules"] = memory.get("modules") or []
    return hardware


def hardware_from_inventory_result(
    inv_result: dict[str, Any],
    *,
    legacy_hwinfo_fn: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Return `/v1/hardware` response from an inventory runner result.

    `legacy_hwinfo_fn` is only called when inventory collection fails, preserving
    the historical fallback behavior while keeping this module subprocess-free.
    """
    if not inv_result.get("ok"):
        legacy = legacy_hwinfo_fn()
        return {
            "ok": True,
            "source": "legacy_hwinfo_fallback",
            "hardware": legacy,
            "hwinfo": legacy,
            "inventory_error": inv_result,
        }

    inv = inv_result.get("inventory") or {}
    hardware = normalize_inventory_hardware(inv)
    return {
        "ok": True,
        "source": "inventory.py",
        "hardware": hardware,
        "hwinfo": hardware,
        "inventory": inv,
        "exit_code": inv_result.get("exit_code"),
        "stderr": inv_result.get("stderr", ""),
    }
