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
        # v3.88.x sensor probes: also expose them on the flat
        # hardware object so /v1/hardware consumers (Doctor tab,
        # legacy scripts) can find them without diving into the
        # raw inventory tree.
        "thermal_detail": inv.get("thermal_detail") or {},
        "fans": inv.get("fans") or {},
        "battery": inv.get("battery") or {},
        "audio": inv.get("audio") or {},
        "disk_smart": inv.get("disk_smart") or {},
        # v3.88.1 agent-focused probes
        "top_processes": inv.get("top_processes") or {},
        "listening_ports": inv.get("listening_ports") or {},
        "systemd_failed": inv.get("systemd_failed") or {},
        "boot_time": inv.get("boot_time") or {},
        "kernel_modules": inv.get("kernel_modules") or {},
        # v3.88.3 agent-focused probes
        "containers": inv.get("containers") or {},
        "systemd_timers": inv.get("systemd_timers") or {},
        "network_io": inv.get("network_io") or {},
        "updates_available": inv.get("updates_available") or {},
        "logged_users": inv.get("logged_users") or {},
        "cpu_vulnerabilities": inv.get("cpu_vulnerabilities") or {},
        # v3.88.4 extended agent context probes
        "python_venvs": inv.get("python_venvs") or {},
        "git_repos": inv.get("git_repos") or {},
        "env_secret_names": inv.get("env_secret_names") or {},
        "crontab_entries": inv.get("crontab_entries") or {},
        "dns_resolvers": inv.get("dns_resolvers") or {},
        "dmesg_errors": inv.get("dmesg_errors") or {},
        "journal_errors": inv.get("journal_errors") or {},
        "virtualization": inv.get("virtualization") or {},
        "time_sync": inv.get("time_sync") or {},
        "firewall_status": inv.get("firewall_status") or {},
        "network": inv.get("network") or {},
        "displays": inv.get("displays") or {},
        "runtimes": inv.get("runtimes") or {},
        "package_managers": inv.get("package_managers") or {},
        "browsers": inv.get("browsers") or {},
        "services": inv.get("services") or {},
    }

    # aliases expected by older dashboard/cards.
    hardware["ram_total_gb"] = memory.get("total_gb")
    hardware["ram_used_gb"] = memory.get("used_gb")
    hardware["ram_avail_gb"] = memory.get("available_gb")
    hardware["ram_modules"] = memory.get("modules") or []
    return hardware


def hardware_from_inventory_result(
    inv_result: dict[str, Any],
    *,
    hwinfo_fn: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Return `/v1/hardware` response from an inventory runner result.

    `hwinfo_fn` is only called when inventory collection fails, preserving
    the historical fallback behavior while keeping this module subprocess-free.
    """
    if not inv_result.get("ok"):
        fallback = hwinfo_fn()
        return {
            "ok": True,
            "source": "hwinfo_fallback",
            "hardware": fallback,
            "hwinfo": fallback,
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
