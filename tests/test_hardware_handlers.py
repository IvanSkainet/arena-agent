"""Hardware handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import HandlerContext  # noqa: E402
from arena.inventory.handlers import make_hardware_handlers  # noqa: E402


def test_hardware_handlers_are_factory_outputs():
    ctx = HandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        slow_executor=ub._SLOW_EXECUTOR,
        inventory_sync=ub._inventory_sync,
        hardware_sync=ub._hardware_from_inventory_sync,
    )
    handlers = make_hardware_handlers(ctx)
    assert callable(handlers.inventory)
    assert callable(handlers.hardware)
    assert callable(handlers.hwinfo)


def test_unified_routes_use_extracted_hardware_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/inventory") in paths
    assert ("GET", "/v1/hardware") in paths
    assert ("GET", "/v1/hwinfo") in paths
