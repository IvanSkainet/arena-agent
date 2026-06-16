"""auth runtime wiring."""
from __future__ import annotations

import time
from typing import Any, MutableMapping


def build_auth_runtime(g: MutableMapping[str, Any]) -> dict[str, Any]:
    users_file = g["APP_DIR"] / "users.json"
    user_store = g["UserStore"](users_file, log_warning=g["log"].warning, log_debug=g["log"].debug)
    auth_runtime_ctx = g["AuthRuntimeContext"](
        user_store=user_store,
        rate_limit_lock=g["_rate_limit_lock"],
        rate_limit_store=g["_rate_limit_store"],
        cors_json_response=g["_cors_json_response"],
        log_warning=g["log"].warning,
        now=time.time,
    )
    auth_runtime = g["make_auth_runtime"](auth_runtime_ctx)
    return {
        "_USERS_FILE": users_file,
        "_user_store": user_store,
        "_auth_runtime_ctx": auth_runtime_ctx,
        "_auth_runtime": auth_runtime,
        "_load_users": auth_runtime.load_users,
        "check_auth_with_role": auth_runtime.check_auth_with_role,
        "check_auth": auth_runtime.check_auth,
        "require_auth": auth_runtime.require_auth,
    }


__all__ = ["build_auth_runtime"]
