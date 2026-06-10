"""Skills handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import SkillHandlerContext  # noqa: E402
from arena.skills.handlers import make_skill_handlers  # noqa: E402


def test_skill_handlers_factory_outputs():
    ctx = SkillHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        skills_list_with_cache=ub._skills_list_sync_with_cache,
        skills_cache_reset=ub._skills_cache_reset,
        skill_install_sync=ub._skill_install_sync,
        skill_uninstall_sync=ub._skill_uninstall_sync,
        skills_run_sync=ub._skills_run_sync,
        skill_path_is_safe=ub._skill_path_is_safe,
        audit=ub.audit,
        log_info=ub.log.info,
    )
    handlers = make_skill_handlers(ctx)
    assert callable(handlers.skills)
    assert callable(handlers.install)
    assert callable(handlers.uninstall)
    assert callable(handlers.run)
    assert callable(handlers.reload)


def test_unified_routes_use_extracted_skill_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/skills") in paths
    assert ("POST", "/v1/skills/install") in paths
    assert ("POST", "/v1/skills/uninstall") in paths
    assert ("POST", "/v1/skills/run") in paths
    assert ("POST", "/v1/skills/reload") in paths
