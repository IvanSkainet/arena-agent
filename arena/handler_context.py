"""Compatibility facade for shared handler context objects."""
from __future__ import annotations

from arena.contexts import (
    AdminHandlerContext,
    AgenticHandlerContext,
    AlertsHandlerContext,
    ApiV2HandlerContext,
    BatchHandlerContext,
    BrowserBrowseHandlerContext,
    BrowserFetchHandlerContext,
    CdpAdvancedHandlerContext,
    CdpBasicHandlerContext,
    CdpCookiesHandlerContext,
    CdpDiagnosticHandlerContext,
    CdpInterceptHandlerContext,
    CdpNetworkHandlerContext,
    CdpPageHandlerContext,
    CdpSessionHandlerContext,
    CdpTabsHandlerContext,
    ClusterHandlerContext,
    ControlLeaseHandlerContext,
    DesktopHandlerContext,
    EventHandlerContext,
    ExecHandlerContext,
    ExtensionBridgeHandlerContext,
    FileHandlerContext,
    FileWatchHandlerContext,
    GatewayHandlerContext,
    GrpcHandlerContext,
    GuiHandlerContext,
    HandlerContext,
    McpHandlerContext,
    MemoryHandlerContext,
    MissionLifecycleHandlerContext,
    ObservabilityHandlerContext,
    PlannerHandlerContext,
    ProfileHandlerContext,
    PublicHandlerContext,
    RateLimitHandlerContext,
    RelayHandlerContext,
    ResourceHandlerContext,
    RuntimeObservabilityHandlerContext,
    SandboxHandlerContext,
    ServiceHandlerContext,
    SkillHandlerContext,
    SystemHandlerContext,
    TaskHandlerContext,
    TlsHandlerContext,
    TracingHandlerContext,
    UserHandlerContext,
    WatchdogHandlerContext,
)

__all__ = ['HandlerContext', 'PublicHandlerContext', 'FileHandlerContext', 'ExecHandlerContext', 'GatewayHandlerContext', 'GuiHandlerContext', 'ServiceHandlerContext', 'DesktopHandlerContext', 'ControlLeaseHandlerContext', 'SystemHandlerContext', 'UserHandlerContext', 'AdminHandlerContext', 'BrowserFetchHandlerContext', 'BrowserBrowseHandlerContext', 'ProfileHandlerContext', 'CdpBasicHandlerContext', 'CdpDiagnosticHandlerContext', 'CdpSessionHandlerContext', 'CdpPageHandlerContext', 'CdpTabsHandlerContext', 'CdpCookiesHandlerContext', 'CdpNetworkHandlerContext', 'CdpInterceptHandlerContext', 'CdpAdvancedHandlerContext', 'RelayHandlerContext', 'TaskHandlerContext', 'SkillHandlerContext', 'ResourceHandlerContext', 'MissionLifecycleHandlerContext', 'PlannerHandlerContext', 'AgenticHandlerContext', 'MemoryHandlerContext', 'ObservabilityHandlerContext', 'TracingHandlerContext', 'ApiV2HandlerContext', 'AlertsHandlerContext', 'RateLimitHandlerContext', 'RuntimeObservabilityHandlerContext', 'BatchHandlerContext', 'TlsHandlerContext', 'SandboxHandlerContext', 'ClusterHandlerContext', 'GrpcHandlerContext', 'ExtensionBridgeHandlerContext', 'EventHandlerContext', 'FileWatchHandlerContext', 'WatchdogHandlerContext', 'McpHandlerContext']

for _name in __all__:
    try:
        globals()[_name].__module__ = __name__
    except Exception:
        pass
