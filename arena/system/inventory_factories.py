"""Runtime sync factories for inventory/hardware helpers."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, MutableMapping


def make_hwinfo_sync(*, collect_hwinfo_fn: Callable[..., dict], subprocess_kwargs_fn: Callable[[], dict[str, Any]]):
    def _hwinfo_sync() -> dict:
        """Collect extended hardware info. Cross-platform."""
        return collect_hwinfo_fn(subprocess_kwargs_fn=subprocess_kwargs_fn)

    return _hwinfo_sync


def make_inventory_sync(
    *,
    run_inventory_fn: Callable[..., dict],
    bridge_dir: Path,
    root_agent: Path,
    python_executable: str | None = None,
):
    def _inventory_sync(section: str | None = None, fmt: str = "text", timeout: int = 30) -> dict:
        """Run inventory.py and return the result."""
        return run_inventory_fn(
            bridge_dir=bridge_dir,
            root_agent=root_agent,
            section=section,
            fmt=fmt,
            timeout=timeout,
            python_executable=python_executable or sys.executable or "python3",
        )

    return _inventory_sync


def make_hardware_from_inventory_sync(
    *,
    globals_ref: MutableMapping[str, Any],
    hardware_from_inventory_result_fn: Callable[..., dict],
):
    def _hardware_from_inventory_sync(timeout: int = 45) -> dict:
        """Return one normalized hardware/system inventory payload."""
        # Deliberately resolve through globals_ref to preserve monkeypatch
        # behavior for tests and callers that replace unified_bridge._inventory_sync.
        inv_result = globals_ref["_inventory_sync"](None, "json", timeout)
        return hardware_from_inventory_result_fn(inv_result, hwinfo_fn=globals_ref["_hwinfo_sync"])

    return _hardware_from_inventory_sync
