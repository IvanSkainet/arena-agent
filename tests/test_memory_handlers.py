"""Memory handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import MemoryHandlerContext  # noqa: E402
from arena.memory.handlers import make_memory_handlers  # noqa: E402


def test_memory_handlers_factory_outputs():
    ctx = MemoryHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        search_facts_paged=ub._search_facts_paged,
        list_profiles=ub._list_memory_profiles,
        write_fact=ub._write_fact,
        delete_fact=ub._delete_fact,
        recall_sync=ub._recall_sync,
        recall_digest_sync=ub._recall_digest_sync,
        audit=ub.audit,
        utc_now=ub.utc_now,
    )
    handlers = make_memory_handlers(ctx)
    assert callable(handlers.memory_get)
    assert callable(handlers.memory_set)
    assert callable(handlers.memory_delete)
    assert callable(handlers.recall)
    assert callable(handlers.recall_digest)


def test_unified_routes_use_extracted_memory_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/memory") in paths
    assert ("POST", "/v1/memory") in paths
    assert ("DELETE", "/v1/memory") in paths
    assert ("GET", "/v1/recall") in paths
    assert ("GET", "/v1/recall/digest") in paths
