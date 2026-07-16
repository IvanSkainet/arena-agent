"""Inventory text formatter. Uses the same registry as the collector
so adding a probe with a ``format_lines`` function is enough — no
edit here required.
"""
from __future__ import annotations

from arena.inventory.registry import REGISTRY


def format_text(data: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"  Arena System Inventory — generated {data.get('generated_at', '')}")
    lines.append("=" * 70)

    for section in REGISTRY:
        if section.name not in data:
            continue
        d = data[section.name]
        if not d:
            continue
        if isinstance(d, dict) and d.get("error"):
            lines.append(f"\n### {section.label}")
            lines.append(f"  error: {d['error']}")
            continue
        # Skip sections that opted out of text formatting (they're
        # too noisy to include by default — pci/usb/storage_devices).
        if section.format_lines is None:
            continue
        section_lines = section.format_lines(d)
        if not section_lines:
            continue
        lines.append(f"\n### {section.label}")
        lines.extend(section_lines)

    return "\n".join(lines) + "\n"
