"""Compatibility factories for system helper functions."""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any, Callable


def make_check_internet_sync(check_internet_fn: Callable[[], bool]) -> Callable[[], bool]:
    def _check_internet_sync() -> bool:
        return check_internet_fn()

    return _check_internet_sync


def make_doctor_sync(
    *,
    run_doctor_fn: Callable[..., dict[str, Any]],
    version: str,
    bridge_dir: Path,
    memory_dir: Path,
    missions_dir: Path,
    facts_count_fn: Callable[[], int],
    internet_check_fn: Callable[[], bool],
    home_dir: Path,
) -> Callable[[str], dict[str, Any]]:
    def _doctor_sync(token: str) -> dict[str, Any]:
        return run_doctor_fn(
            version=version,
            token=token,
            bridge_dir=bridge_dir,
            memory_dir=memory_dir,
            missions_dir=missions_dir,
            facts_count_fn=facts_count_fn,
            internet_check_fn=internet_check_fn,
            home_dir=home_dir,
        )

    return _doctor_sync


def make_play_beep_sync(
    *,
    play_beep_fn: Callable[..., dict[str, Any]],
    subprocess_kwargs_fn: Callable[[], dict[str, Any]],
) -> Callable[[str, int, int], dict[str, Any]]:
    def _play_beep_sync(beep_type: str, freq: int, dur: int) -> dict[str, Any]:
        return play_beep_fn(beep_type, freq, dur, subprocess_kwargs_fn=subprocess_kwargs_fn)

    return _play_beep_sync


def make_sysinfo_cim_sync(
    *,
    sysinfo_cim_cpu_counts_fn: Callable[..., tuple[int, int]],
    subprocess_kwargs_fn: Callable[[], dict[str, Any]],
) -> Callable[[], tuple[int, int]]:
    def _sysinfo_cim_sync() -> tuple[int, int]:
        return sysinfo_cim_cpu_counts_fn(subprocess_kwargs_fn=subprocess_kwargs_fn)

    return _sysinfo_cim_sync


def make_sysinfo_sync(
    *,
    collect_sysinfo_fn: Callable[..., dict[str, Any]],
    clean_platform_name_fn: Callable[[], str],
    subprocess_kwargs_fn: Callable[[], dict[str, Any]],
) -> Callable[[Any], dict[str, Any]]:
    def _sysinfo_sync(root) -> dict[str, Any]:
        return collect_sysinfo_fn(
            root=root,
            clean_platform_name_fn=clean_platform_name_fn,
            subprocess_kwargs_fn=subprocess_kwargs_fn,
        )

    return _sysinfo_sync


def make_common_status(
    *,
    version: str,
    audit_path: Path,
    clean_platform_name_fn: Callable[[], str],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def common_status(cfg: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "service": "arena-unified-bridge",
            "version": version,
            "host": socket.gethostname(),
            "platform": clean_platform_name_fn(),
            "python": sys.version.split()[0],
            "profile": cfg["profile"],
            "root": str(cfg["root"]),
            "auth_required_for_exec": True,
            "active_exec": cfg["active_exec"],
            "max_concurrent": cfg["max_concurrent"],
            "audit": str(audit_path),
        }

    return common_status
