"""User handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.auth.handlers import make_user_handlers  # noqa: E402
from arena.handler_context import UserHandlerContext  # noqa: E402


def test_user_handlers_factory_outputs():
    ctx = UserHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        check_auth_with_role=ub.check_auth_with_role,
        list_users=ub._user_store.list_users_for_response,
        add_or_update_user=ub._user_store.add_or_update_user,
        remove_user=ub._user_store.remove_user,
        token_generator=ub.b64_token,
        audit=ub.audit,
        log_info=ub.log.info,
    )
    handlers = make_user_handlers(ctx)
    assert callable(handlers.users)


def test_user_routes_registered():
    app = ub.make_app({"token": "test", "profile": "owner-shell", "root": "/tmp", "active_exec": 0, "max_concurrent": 3, "audit": "audit"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/users") in paths
    assert ("POST", "/v1/users") in paths
    assert ("DELETE", "/v1/users") in paths
