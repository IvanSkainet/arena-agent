"""unified_bridge import surface: core imports."""
from __future__ import annotations

# ============================================================================
# VERSION & CONSTANTS
# ============================================================================
# Version, filesystem paths and tunable limits now live in arena/constants.py;
# re-exported here so existing references (`unified_bridge.VERSION`, `APP_DIR`, …)
# keep working.
from arena.constants import (  # noqa: E402,F401
    APP_DIR,
    AUDIT,
    AUDIT_CMD_LIMIT,
    BRIDGE_DIR,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MAX_OUTPUT,
    MAX_BODY,
    TOKEN_FILE,
    VERSION,
)

# ============================================================================
# DESKTOP CONTROL STATE (v2.9.0)
# ============================================================================
# The control-lease state and helpers now live in arena/control.py; re-exported
# here so existing references (`unified_bridge._control_state`, etc.) keep working.
from arena.bootstrap import daemonize as _daemonize_runtime, ensure_session_env as _ensure_session_env_runtime, get_bridge_port as _get_bridge_port_runtime, load_config_file as _load_config_file_runtime, resolve_token as _resolve_token_runtime, setup_logging as _setup_logging_runtime  # noqa: E402,F401
from arena.errors import (  # noqa: E402,F401
    AuthError,
    BridgeError,
    BridgeTimeoutError,
    ErrorMiddlewareContext,
    ForbiddenError,
    NotFoundError,
    ResourceError,
    ValidationError,
    make_error_middleware,
)
from arena.control import (  # noqa: E402,F401
    _control_check,
    _control_lock,
    _control_record_agent_action,
    _control_state,
)


# Security primitives (command blocklist, desktop-input-injection guard, and
# SSRF URL validation) now live in arena/security.py. Re-exported here so
# existing references and tests (`unified_bridge.blocked_reason`, etc.) keep working.
from arena.security import (  # noqa: E402,F401
    BLOCK_PATTERNS,
    _INPUT_INJECTION_PATTERNS,
    _is_input_injection_cmd,
    _validate_url,
    blocked_reason,
)
from arena.rate_limit import (  # noqa: E402,F401
    _rate_limit_lock,
    _rate_limit_max,
    _rate_limit_store,
    _rate_limit_window,
    _rl_v2_config,
    _rl_v2_lock,
    _rl_v2_store,
    check_rate_limit as rl_check_rate_limit,
    check_rate_limit_v2 as rl_check_rate_limit_v2,
    rate_limit_stats,
    update_rate_limit_config,
)
from arena.auth.users import UserStore  # noqa: E402,F401
from arena.auth.runtime import AuthRuntimeContext, make_auth_runtime  # noqa: E402,F401
from arena.auth.handlers import make_user_handlers  # noqa: E402,F401
from arena.files.handlers import make_file_handlers  # noqa: E402,F401
from arena.exec.runner import (  # noqa: E402,F401
    ACTIVE_PROCESSES,
    active_processes_snapshot,
    run_shell_command,
)
from arena.exec.handlers import make_exec_handlers  # noqa: E402,F401
from arena.admin.sync_factories import (  # noqa: E402,F401
    make_cloudflared_funnel_action_sync,
    make_sys_funnel_sync,
    make_tailscale_funnel_action_sync,
    make_token_path,
    make_token_regen_sync,
)
from arena.admin.runtime import (  # noqa: E402,F401
    CLOUDFLARED_STATE as _CLOUDFLARED_STATE,
    cloudflared_funnel_action as _cloudflared_funnel_action_runtime,
    sys_funnel_status as _sys_funnel_status_runtime,
    tailscale_funnel_action as _tailscale_funnel_action_runtime,
    token_regenerate as _token_regenerate_runtime,
)
from arena.admin.handlers import make_admin_handlers  # noqa: E402,F401
from arena.public.handlers import make_public_handlers  # noqa: E402,F401
from arena.gateway.runtime import GW_WHITELIST, gw_allowed, gw_run_sync as _gw_run_sync  # noqa: E402,F401
from arena.gateway.handlers import make_gateway_handlers  # noqa: E402,F401
from arena.mcp.runtime import (  # noqa: E402,F401
    MCP_SESSIONS,
    MCP_SESSION_MAX_AGE_MS,
    cleanup_mcp_sessions as _mcp_cleanup_sessions,
    now_ms,
    sid,
)
from arena.mcp.handlers import make_mcp_handlers  # noqa: E402,F401
from arena.mcp.tools import McpToolContext, make_mcp_tool_runtime  # noqa: E402,F401
from arena.events.runtime import EVENT_SUBSCRIBERS as _event_subscribers, emit_event as _events_emit_event  # noqa: E402,F401
from arena.events.handlers import make_event_handlers  # noqa: E402,F401
from arena.watchdog.runtime import (  # noqa: E402,F401
    WATCHDOG_STATE as _watchdog_state,
    start_watchdog as _watchdog_start,
    stop_watchdog as _watchdog_stop,
    watchdog_loop as _watchdog_loop,
)
from arena.watchdog.handlers import make_watchdog_handlers  # noqa: E402,F401
from arena.gui.handlers import (  # noqa: E402,F401
    DASHBOARD_V2_HTML as _DASHBOARD_V2_HTML,
    GUI_LOGIN_HTML as _GUI_LOGIN_HTML,
    make_gui_handlers,
)
from arena.grpc.runtime import (  # noqa: E402,F401
    GRPC_CONFIG as _grpc_config,
    grpc_handler as _grpc_handler,
    grpc_server_loop as _grpc_server_loop,
    grpc_server_task as _grpc_server_task,
    start_grpc_server,
    stop_grpc_server,
)
from arena.grpc.handlers import make_grpc_handlers  # noqa: E402,F401
from arena.profiles.handlers import (  # noqa: E402,F401
    PROFILES_DIR as _PROFILES_DIR,
    ensure_profiles_dir as _profiles_ensure_profiles_dir,
    make_profile_handlers,
)
from arena.cluster.runtime import (  # noqa: E402,F401
    CLUSTER_CONFIG as _cluster_config,
    CLUSTER_STATE as _cluster_state,
    cluster_heartbeat_loop as _cluster_runtime_heartbeat_loop,
    get_node_id as _cluster_get_node_id,
    start_cluster_heartbeat,
    stop_cluster_heartbeat,
)
from arena.cluster.handlers import make_cluster_handlers  # noqa: E402,F401
from arena.sandbox.runtime import SANDBOX_CONFIG as _sandbox_config, run_sandboxed as _sandbox_run_sandboxed  # noqa: E402,F401
from arena.sandbox.handlers import make_sandbox_handlers  # noqa: E402,F401
from arena.tls.handlers import (  # noqa: E402,F401
    TLS_CONFIG as _tls_config,
    generate_self_signed_cert as _tls_generate_self_signed_cert,
    get_tailscale_cert as _tls_get_tailscale_cert,
    make_tls_handlers,
)
from arena.batch.handlers import make_batch_handlers  # noqa: E402,F401
from arena.api_v2.handlers import (  # noqa: E402,F401
    DEPRECATED_ENDPOINTS as _DEPRECATED_ENDPOINTS,
    cfg_get_max_timeout,
    make_v2_handlers,
)

__all__ = [name for name in globals() if not name.startswith("__")]
