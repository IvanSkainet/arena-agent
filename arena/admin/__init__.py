"""Admin/network management domain package."""

from arena.admin.handlers import AdminHandlers, make_admin_handlers
from arena.admin.runtime import (
    CLOUDFLARED_STATE,
    browseract_doctor,
    browseract_status,
    cloudflared_funnel_action,
    sys_funnel_status,
    tailscale_funnel_action,
    token_regenerate,
    tunnels_active,
    tunnels_start,
    tunnels_status,
    tunnels_stop,
    zerotier_network_action,
    zerotier_status,
)

__all__ = [
    "CLOUDFLARED_STATE",
    "cloudflared_funnel_action",
    "sys_funnel_status",
    "tailscale_funnel_action",
    "token_regenerate",
    "zerotier_status",
    "zerotier_network_action",
    "tunnels_status",
    "tunnels_active",
    "tunnels_start",
    "tunnels_stop",
    "browseract_status",
    "browseract_doctor",
    "AdminHandlers",
    "make_admin_handlers",
]
