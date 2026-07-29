"""Whole-ship status/preflight aggregation for Arena Unified Bridge."""

from importlib import import_module as _import_module

_status_module = _import_module("arena.ship.status")
ship_status = _status_module.status
preflight = _status_module.preflight

__all__ = ["ship_status", "preflight"]
