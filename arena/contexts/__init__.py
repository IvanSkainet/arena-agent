"""Domain-grouped handler context dataclasses."""
from __future__ import annotations

from arena.contexts.browser import BrowserBrowseHandlerContext, BrowserFetchHandlerContext, ProfileHandlerContext
from arena.contexts.cdp import (
    CdpAdvancedHandlerContext,
    CdpBasicHandlerContext,
    CdpCookiesHandlerContext,
    CdpDiagnosticHandlerContext,
    CdpInterceptHandlerContext,
    CdpNetworkHandlerContext,
    CdpPageHandlerContext,
    CdpSessionHandlerContext,
    CdpTabsHandlerContext,
)
from arena.contexts.core import (
    ExecHandlerContext,
    FileHandlerContext,
    GatewayHandlerContext,
    GuiHandlerContext,
    HandlerContext,
    PublicHandlerContext,
)
from arena.contexts.domain import (
    AgenticHandlerContext,
    MemoryHandlerContext,
    MissionLifecycleHandlerContext,
    PlannerHandlerContext,
    ResourceHandlerContext,
    SkillHandlerContext,
    TaskHandlerContext,
)
from arena.contexts.integration import (
    BatchHandlerContext,
    ClusterHandlerContext,
    EventHandlerContext,
    ExtensionBridgeHandlerContext,
    FileWatchHandlerContext,
    GrpcHandlerContext,
    McpHandlerContext,
    SandboxHandlerContext,
    TlsHandlerContext,
    WatchdogHandlerContext,
)
from arena.contexts.observability import (
    AlertsHandlerContext,
    ApiV2HandlerContext,
    ObservabilityHandlerContext,
    RateLimitHandlerContext,
    RuntimeObservabilityHandlerContext,
    TracingHandlerContext,
)
from arena.contexts.platform import (
    AdminHandlerContext,
    ControlLeaseHandlerContext,
    DesktopHandlerContext,
    ServiceHandlerContext,
    SystemHandlerContext,
    UserHandlerContext,
)

__all__ = ['HandlerContext', 'PublicHandlerContext', 'FileHandlerContext', 'ExecHandlerContext', 'GatewayHandlerContext', 'GuiHandlerContext', 'ServiceHandlerContext', 'DesktopHandlerContext', 'ControlLeaseHandlerContext', 'SystemHandlerContext', 'UserHandlerContext', 'AdminHandlerContext', 'BrowserFetchHandlerContext', 'BrowserBrowseHandlerContext', 'ProfileHandlerContext', 'CdpBasicHandlerContext', 'CdpDiagnosticHandlerContext', 'CdpSessionHandlerContext', 'CdpPageHandlerContext', 'CdpTabsHandlerContext', 'CdpCookiesHandlerContext', 'CdpNetworkHandlerContext', 'CdpInterceptHandlerContext', 'CdpAdvancedHandlerContext', 'TaskHandlerContext', 'SkillHandlerContext', 'ResourceHandlerContext', 'MissionLifecycleHandlerContext', 'PlannerHandlerContext', 'AgenticHandlerContext', 'MemoryHandlerContext', 'ObservabilityHandlerContext', 'TracingHandlerContext', 'ApiV2HandlerContext', 'AlertsHandlerContext', 'RateLimitHandlerContext', 'RuntimeObservabilityHandlerContext', 'BatchHandlerContext', 'TlsHandlerContext', 'SandboxHandlerContext', 'ClusterHandlerContext', 'GrpcHandlerContext', 'ExtensionBridgeHandlerContext', 'EventHandlerContext', 'FileWatchHandlerContext', 'WatchdogHandlerContext', 'McpHandlerContext']
