"""Cluster runtime and handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.cluster.handlers import make_cluster_handlers  # noqa: E402
from arena.cluster.runtime import CLUSTER_CONFIG, CLUSTER_STATE, get_node_id, stop_cluster_heartbeat  # noqa: E402
from arena.handler_context import ClusterHandlerContext  # noqa: E402


def test_cluster_state_reexported_for_compatibility():
    assert ub._cluster_config is CLUSTER_CONFIG
    assert ub._cluster_state is CLUSTER_STATE
    assert isinstance(get_node_id(), str)
    assert "role" in CLUSTER_STATE


def test_cluster_handlers_factory_outputs():
    ctx = ClusterHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        get_node_id=ub._get_node_id,
        start_heartbeat=lambda: None,
        stop_heartbeat=stop_cluster_heartbeat,
        audit=ub.audit,
        log_info=ub.log.info,
    )
    handlers = make_cluster_handlers(ctx)
    assert callable(handlers.cluster)


def test_cluster_routes_registered():
    app = ub.make_app({
        "token": "test",
        "profile": "owner-shell",
        "root": Path("/tmp"),
        "active_exec": 0,
        "max_concurrent": 3,
        "audit": "audit",
        "timeout": 60,
        "max_timeout": 3600,
        "max_output": 2000000,
        "allow_any_cwd": False,
        "semaphore": asyncio.Semaphore(1),
    })
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/cluster") in paths
    assert ("POST", "/v1/cluster") in paths
