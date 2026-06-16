"""Compatibility facade for shared handler context objects."""
from __future__ import annotations

from arena.contexts import (
    HandlerContext,
    PublicHandlerContext,
    FileHandlerContext,
    ExecHandlerContext,
    GatewayHandlerContext,
    GuiHandlerContext,
    ServiceHandlerContext,
    DesktopHandlerContext,
    ControlLeaseHandlerContext,
    SystemHandlerContext,
    UserHandlerContext,
    AdminHandlerContext,
    BrowserFetchHandlerContext,
    BrowserBrowseHandlerContext,
    ProfileHandlerContext,
    CdpBasicHandlerContext,
    CdpDiagnosticHandlerContext,
    CdpSessionHandlerContext,
    CdpPageHandlerContext,
    CdpTabsHandlerContext,
    CdpCookiesHandlerContext,
    CdpNetworkHandlerContext,
    CdpInterceptHandlerContext,
    CdpAdvancedHandlerContext,
    TaskHandlerContext,
    SkillHandlerContext,
    ResourceHandlerContext,
    MemoryHandlerContext,
    ObservabilityHandlerContext,
    TracingHandlerContext,
    ApiV2HandlerContext,
    AlertsHandlerContext,
    RateLimitHandlerContext,
    RuntimeObservabilityHandlerContext,
    BatchHandlerContext,
    TlsHandlerContext,
    SandboxHandlerContext,
    ClusterHandlerContext,
    GrpcHandlerContext,
    EventHandlerContext,
    WatchdogHandlerContext,
    McpHandlerContext,
)

__all__ = ['HandlerContext', 'PublicHandlerContext', 'FileHandlerContext', 'ExecHandlerContext', 'GatewayHandlerContext', 'GuiHandlerContext', 'ServiceHandlerContext', 'DesktopHandlerContext', 'ControlLeaseHandlerContext', 'SystemHandlerContext', 'UserHandlerContext', 'AdminHandlerContext', 'BrowserFetchHandlerContext', 'BrowserBrowseHandlerContext', 'ProfileHandlerContext', 'CdpBasicHandlerContext', 'CdpDiagnosticHandlerContext', 'CdpSessionHandlerContext', 'CdpPageHandlerContext', 'CdpTabsHandlerContext', 'CdpCookiesHandlerContext', 'CdpNetworkHandlerContext', 'CdpInterceptHandlerContext', 'CdpAdvancedHandlerContext', 'TaskHandlerContext', 'SkillHandlerContext', 'ResourceHandlerContext', 'MemoryHandlerContext', 'ObservabilityHandlerContext', 'TracingHandlerContext', 'ApiV2HandlerContext', 'AlertsHandlerContext', 'RateLimitHandlerContext', 'RuntimeObservabilityHandlerContext', 'BatchHandlerContext', 'TlsHandlerContext', 'SandboxHandlerContext', 'ClusterHandlerContext', 'GrpcHandlerContext', 'EventHandlerContext', 'WatchdogHandlerContext', 'McpHandlerContext']

for _name in __all__:
    try:
        globals()[_name].__module__ = __name__
    except Exception:
        pass
