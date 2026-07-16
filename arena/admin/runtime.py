"""Runtime helper facade for admin/network management endpoints."""
from __future__ import annotations

from arena.admin.cloudflared import CLOUDFLARED_STATE, cloudflared_funnel_action
from arena.admin.tailscale import sys_funnel_status, tailscale_funnel_action
from arena.admin.zerotier import zerotier_status, zerotier_network_action
from arena.admin.zerotier_peers import zerotier_peers
from arena.admin.browseract import browseract_status, browseract_doctor
from arena.admin.tunnels import tunnels_status, tunnels_active, tunnels_start, tunnels_stop
from arena.admin.token import token_regenerate

__all__ = [
    "CLOUDFLARED_STATE",
    "cloudflared_funnel_action",
    "sys_funnel_status",
    "tailscale_funnel_action",
    "token_regenerate",
    "zerotier_status",
    "zerotier_network_action",
    "zerotier_peers",
    "tunnels_status",
    "tunnels_active",
    "tunnels_start",
    "tunnels_stop",
    "browseract_status",
    "browseract_doctor",
]
