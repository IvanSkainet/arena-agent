"""Service runtime modularization smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.service.runtime as sr  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_service_helpers_reexported_from_module():
    assert ub._service_info_sync is sr._service_info_sync
    assert ub._sys_svc_sync is sr._sys_svc_sync
    assert ub._spawn_respawn_helper is sr._spawn_respawn_helper


def test_service_helpers_return_basic_shape():
    info = sr._service_info_sync()
    assert info["ok"] is True
    assert "running_as" in info
    assert "pid" in info

    svc = sr._sys_svc_sync()
    assert svc["ok"] is True
    assert "bridge_processes" in svc
