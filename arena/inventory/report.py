"""Inventory aggregation. Reads the registry as the single source of
truth for what probes exist; text formatting also lives there.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from arena.inventory.registry import REGISTRY

# Back-compat alias: older code imports `SECTIONS` from here as
# `list[tuple[name, collector]]`.
SECTIONS = [(s.name, s.collector) for s in REGISTRY]


# Probes are independent and spend nearly all their time waiting -- on
# subprocesses, WMI, or the filesystem -- so they are collected in
# parallel. Measured serially on the reporting machine's Windows box:
# 87.4s total against a 90s ceiling, with `python_venvs` (31.6s) and
# `git_repos` (15.7s) alone making up 54% of it (#385).
#
# Threads rather than processes: the work is I/O-bound, so the GIL is
# released for the part that costs, and a thread pool avoids paying a
# fresh interpreter start per probe on Windows.
_MAX_WORKERS = 8


def _run_probe(section) -> tuple[str, Any]:
    """Run one probe, turning any exception into an error payload.

    Same contract as before: a probe that raises must not take the run
    down with it, and the caller sees `{"error": ...}` in its slot.
    """
    try:
        return section.name, section.collector()
    except Exception as e:  # noqa: BLE001 -- probes must never crash the run
        return section.name, {"error": str(e)}


def collect(only_section: Optional[str] = None) -> dict:
    """Run every registered probe (or one by name) and assemble the
    inventory dict. Probe exceptions become ``{"error": str}`` so
    downstream never sees a raise."""
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "arena-inventory",
        "tool_version": "1.0.0",
    }
    wanted = [s for s in REGISTRY
              if not only_section or s.name == only_section]
    if len(wanted) <= 1:
        # One probe is the `--section` path; a pool would only add
        # thread-startup cost to it.
        for s in wanted:
            name, payload = _run_probe(s)
            result[name] = payload
        return result

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        for name, payload in pool.map(_run_probe, wanted):
            result[name] = payload
    return result


from arena.inventory.text_format import format_text  # noqa: E402,F401
