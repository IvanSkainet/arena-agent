"""Compatibility aggregator for hardware inventory probes."""
from __future__ import annotations

from arena.inventory.probe_cpu_memory import get_cpu, get_memory
from arena.inventory.probe_gpu_board import get_gpu, get_motherboard

__all__ = ["get_cpu", "get_memory", "get_gpu", "get_motherboard"]
