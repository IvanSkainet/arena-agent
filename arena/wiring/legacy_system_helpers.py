# ruff: noqa: F821
"""Legacy system helper wiring for unified_bridge."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, MutableMapping


def build_legacy_system_helpers(g: MutableMapping[str, Any]) -> dict[str, Any]:
    helpers = {
        "_check_internet_sync": g["make_check_internet_sync"](g["check_internet"]),
        "_play_beep_sync": g["make_play_beep_sync"](
            play_beep_fn=g["play_beep"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_sysinfo_cim_sync": g["make_sysinfo_cim_sync"](
            sysinfo_cim_cpu_counts_fn=g["sysinfo_cim_cpu_counts"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_sysinfo_sync": g["make_sysinfo_sync"](
            collect_sysinfo_fn=g["collect_sysinfo"],
            clean_platform_name_fn=g["get_clean_platform_name"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "common_status": g["make_common_status"](
            version=g["VERSION"],
            audit_path=g["AUDIT"],
            clean_platform_name_fn=g["get_clean_platform_name"],
        ),
    }
    g.update(helpers)
    helpers["_doctor_sync"] = g["make_doctor_sync"](
        run_doctor_fn=g["run_doctor"],
        version=g["VERSION"],
        bridge_dir=g["BRIDGE_DIR"],
        memory_dir=g["MEMORY_FILE"].parent,
        missions_dir=g["MISSIONS_DIR"],
        facts_count_fn=lambda: len(g["_load_facts"]()),
        internet_check_fn=helpers["_check_internet_sync"],
        home_dir=Path.home(),
    )
    helpers.update({
        "_hwinfo_sync": g["make_hwinfo_sync"](
            collect_legacy_hwinfo_fn=g["collect_legacy_hwinfo"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_inventory_sync": g["make_inventory_sync"](
            run_inventory_fn=g["run_inventory"],
            bridge_dir=g["BRIDGE_DIR"],
            root_agent=g["ROOT_AGENT"],
            python_executable=os.sys.executable or "python3",
        ),
    })
    g.update(helpers)
    helpers["_hardware_from_inventory_sync"] = g["make_hardware_from_inventory_sync"](
        globals_ref=g,
        hardware_from_inventory_result_fn=g["hardware_from_inventory_result"],
    )
    return helpers


__all__ = ["build_legacy_system_helpers"]
