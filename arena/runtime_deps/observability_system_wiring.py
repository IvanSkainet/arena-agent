"""unified_bridge import surface: observability system wiring imports."""
from __future__ import annotations

from arena.http import (  # noqa: E402,F401
    CORS_HEADERS,
    _cors_json_response,
    cors_json_response,
)
from arena.observability.metrics import (  # noqa: E402,F401
    BRIDGE_METRICS,
    _metrics_lock,
    _record_request,
    record_request,
)
from arena.observability.audit import (  # noqa: E402,F401
    audit_lock,
    audit_stats,
    read_tail as audit_read_tail,
    sanitize_audit_event as audit_sanitize_event,
    write_audit_event,
)
from arena.observability.request_log import (  # noqa: E402,F401
    log_request_response as request_log_response,
    read_request_log,
    request_log_lock,
)
from arena.observability.webhooks import (  # noqa: E402,F401
    fire_webhooks,
    load_webhooks,
    normalize_webhooks_config,
    save_webhooks,
)
from arena.observability.handlers import make_observability_handlers  # noqa: E402,F401
from arena.observability.runtime_handlers import make_runtime_observability_handlers  # noqa: E402,F401
from arena.observability.audit_runtime import AuditRuntimeContext, make_audit_runtime  # noqa: E402,F401
from arena.observability.log_cleanup import LogCleanupContext, make_log_cleanup_runtime  # noqa: E402,F401
from arena.observability.alerts import ALERTS_CONFIG as _ALERTS_CONFIG, make_alert_handlers  # noqa: E402,F401
from arena.observability.ratelimit_handlers import make_rate_limit_handlers  # noqa: E402,F401
from arena.observability.tracing import (  # noqa: E402,F401
    _otel_config,
    _otel_lock,
    _otel_record_span,
    _otel_should_sample,
    _otel_trace_id,
    _otel_traces,
    make_tracing_handlers,
)
from arena.system.handlers import make_system_handlers  # noqa: E402,F401
from arena.system.sysinfo import (  # noqa: E402,F401
    collect_sysinfo,
    sysinfo_cim_cpu_counts,
)
from arena.system.doctor import (  # noqa: E402,F401
    check_internet,
    run_doctor,
)
from arena.system.sound import (  # noqa: E402,F401
    generate_wav_bytes,
    linux_play_beep,
    play_beep,
    winsound_melody,
)
from arena.system.hwinfo_fallback import collect_hwinfo  # noqa: E402,F401
from arena.system.inventory_factories import (  # noqa: E402,F401
    make_hardware_from_inventory_sync,
    make_hwinfo_sync,
    make_inventory_sync,
)
from arena.system.sync_factories import (  # noqa: E402,F401
    make_check_internet_sync,
    make_common_status,
    make_doctor_sync,
    make_play_beep_sync,
    make_sysinfo_cim_sync,
    make_sysinfo_sync,
)
from arena.handler_context import HandlerContext, ServiceHandlerContext, TaskHandlerContext, SkillHandlerContext, DesktopHandlerContext, ControlLeaseHandlerContext, BrowserFetchHandlerContext, BrowserBrowseHandlerContext, CdpBasicHandlerContext, CdpDiagnosticHandlerContext, CdpSessionHandlerContext, CdpPageHandlerContext, CdpTabsHandlerContext, CdpCookiesHandlerContext, CdpNetworkHandlerContext, CdpInterceptHandlerContext, CdpAdvancedHandlerContext, ResourceHandlerContext, MissionLifecycleHandlerContext, PlannerHandlerContext, AgenticHandlerContext, MemoryHandlerContext, ObservabilityHandlerContext, SystemHandlerContext, UserHandlerContext, FileHandlerContext, ExecHandlerContext, GatewayHandlerContext, TracingHandlerContext, ApiV2HandlerContext, BatchHandlerContext, AlertsHandlerContext, RateLimitHandlerContext, TlsHandlerContext, SandboxHandlerContext, ClusterHandlerContext, ProfileHandlerContext, GrpcHandlerContext, EventHandlerContext, FileWatchHandlerContext, WatchdogHandlerContext, GuiHandlerContext, McpHandlerContext, RuntimeObservabilityHandlerContext, PublicHandlerContext, AdminHandlerContext  # noqa: E402,F401
from arena.inventory.handlers import make_hardware_handlers  # noqa: E402,F401
from arena.service.capabilities import make_capabilities_sync  # noqa: E402,F401
from arena.service.handlers import make_service_handlers  # noqa: E402,F401
from arena.tasks.handlers import make_task_handlers  # noqa: E402,F401
from arena.routes import register_routes  # noqa: E402,F401
from arena.app import make_app as _make_arena_app  # noqa: E402,F401
from arena.container import AdminWiringContext, PublicWiringContext, ServiceWiringContext, SystemWiringContext, build_admin_handlers, build_container, build_context_handlers, build_public_handlers, build_service_handlers, build_system_handlers, export_handler_attrs  # noqa: E402,F401
from arena.wiring.early_registries import build_early_handler_registries  # noqa: E402,F401
from arena.wiring.system_public_admin_registries import build_system_public_admin_registries  # noqa: E402,F401
from arena.wiring.hardware_exec_registries import build_hardware_exec_registries  # noqa: E402,F401
from arena.wiring.domain_runtimes import build_memory_resource_browser_runtimes  # noqa: E402,F401
from arena.wiring.service_browser_registries import build_service_browser_registries  # noqa: E402,F401
from arena.wiring.cdp_registries import build_cdp_registries  # noqa: E402,F401
from arena.wiring.desktop_registries import build_desktop_registries  # noqa: E402,F401
from arena.wiring.memory_observability_registries import build_memory_observability_registries  # noqa: E402,F401
from arena.wiring.tasks_skills_resources_registries import build_tasks_skills_resources_registries  # noqa: E402,F401
from arena.wiring.mcp_task_runtime import build_mcp_task_runtimes  # noqa: E402,F401
from arena.wiring.observability_runtime import build_observability_runtimes  # noqa: E402,F401
from arena.wiring.app_lifecycle import build_app_lifecycle  # noqa: E402,F401
from arena.wiring.runtime_wrappers import build_runtime_wrappers  # noqa: E402,F401
from arena.wiring.bridge_runtime import build_bridge_runtime  # noqa: E402,F401
from arena.paths import ArenaPaths  # noqa: E402,F401
from arena.lifecycle import LifecycleContext, make_lifecycle  # noqa: E402,F401
from arena.cli import CliContext, main as _cli_main, serve as _cli_serve, token_cmd as _cli_token_cmd  # noqa: E402,F401

__all__ = [name for name in globals() if not name.startswith("__")]
