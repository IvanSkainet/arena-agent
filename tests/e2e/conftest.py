"""Shared fixtures for the live E2E suite.

The ``bridge`` fixture (a real server process plus a client bound to it) was
written for test_bridge_live.py and is re-exported here rather than moved, so
the browser suite reuses the exact same startup contract -- token handling,
the 40s health deadline, the SIGTERM grace period -- instead of growing a
second, slightly different copy that drifts.
"""
from __future__ import annotations

from tests.e2e.test_bridge_live import bridge  # noqa: F401  # re-exported fixture

__all__ = ["bridge"]
