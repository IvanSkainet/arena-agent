"""Shared fixtures for the live E2E suite.

The ``bridge`` fixture (a real server process plus a client bound to it) was
written for test_bridge_live.py and is re-exported here rather than moved, so
the browser suite reuses the exact same startup contract -- token handling,
the 40s health deadline, the SIGTERM grace period -- instead of growing a
second, slightly different copy that drifts.

Loaded by file path, not as ``tests.e2e.test_bridge_live``: ``tests/`` has no
``__init__.py``, so the dotted import only resolves when the repo root happens
to be on sys.path. It does locally and did not in CI, where every matrix cell
failed collection with ``ModuleNotFoundError: No module named 'tests'``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_LIVE = Path(__file__).resolve().parent / "test_bridge_live.py"
_spec = importlib.util.spec_from_file_location("_arena_e2e_bridge_live", _LIVE)
assert _spec and _spec.loader, f"cannot load {_LIVE}"
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

bridge = _module.bridge

__all__ = ["bridge"]
