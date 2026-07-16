"""Inventory aggregation. Reads the registry as the single source of
truth for what probes exist; text formatting also lives there.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from arena.inventory.registry import REGISTRY

# Back-compat alias: older code imports `SECTIONS` from here as
# `list[tuple[name, collector]]`.
SECTIONS = [(s.name, s.collector) for s in REGISTRY]


def collect(only_section: Optional[str] = None) -> dict:
    """Run every registered probe (or one by name) and assemble the
    inventory dict. Probe exceptions become ``{"error": str}`` so
    downstream never sees a raise."""
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "arena-inventory",
        "tool_version": "1.0.0",
    }
    for s in REGISTRY:
        if only_section and s.name != only_section:
            continue
        try:
            result[s.name] = s.collector()
        except Exception as e:  # noqa: BLE001 -- probes must never crash the run
            result[s.name] = {"error": str(e)}
    return result


from arena.inventory.text_format import format_text  # noqa: E402,F401
