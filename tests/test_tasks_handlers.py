"""Task handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import TaskHandlerContext  # noqa: E402
from arena.tasks.handlers import make_task_handlers  # noqa: E402


def test_task_handlers_factory_outputs():
    ctx = TaskHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        tasks_list_sync=ub._tasks_list_sync,
        task_submit_sync=ub._task_submit_sync,
        tasks_clean_sync=ub._tasks_clean_sync,
        audit=ub.audit,
    )
    handlers = make_task_handlers(ctx)
    assert callable(handlers.tasks_get)
    assert callable(handlers.tasks_post)
    assert callable(handlers.tasks_clean)


def test_unified_routes_use_extracted_task_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/tasks") in paths
    assert ("POST", "/v1/tasks") in paths
    assert ("POST", "/v1/tasks/clean") in paths
