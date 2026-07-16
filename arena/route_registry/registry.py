"""Unified declarative route registry (v3.90.0).

Every HTTP route in the bridge is declared here as a single
``Route`` tuple in the ``ROUTES`` list. The five legacy per-group
files (``core.py``, ``compat.py``, ``desktop.py``, ``domain.py``
and ``cdp.py``) still exist as thin shims that call
``register_group(app, h, group_name)`` -- backward-compatible for
any external code that imports ``register_core_routes`` etc.

Adding a new endpoint = adding ONE tuple to ``ROUTES``. Guard
tests catch duplicates, unknown handlers, malformed paths, and
group drift between this registry and the legacy shims.

Structure of each ``Route``::

    (method: str,           # 'GET', 'POST', 'DELETE', ...
     path: str,             # '/v1/foo/{bar}'
     handler_name: str,     # key in the h[] mapping
     group: str,            # 'core' | 'compat' | 'desktop' |
                            #   'domain' | 'cdp'
     opts: dict | None)     # future: {'auth': 'master', 'rate': ...}

The optional ``opts`` slot is here so we can eventually attach
per-route metadata (auth policy, rate limit tier, OpenAPI
description) in one place instead of scattering it through the
handler code.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Optional

from aiohttp import web


# Type alias for a single route declaration.
Route = tuple[str, str, str, str, Optional[dict[str, Any]]]


# ---------------------------------------------------------------------
# CDP routes: 18 endpoints registered against TWO different prefixes
# (/v1/browser/cdp and /v1/cdp) for backward compatibility. Declared
# once as _CDP_ENDPOINTS then expanded below.
# ---------------------------------------------------------------------

_CDP_ENDPOINTS = [
    # method, subpath, handler
    ("GET",    "/status",              "handle_v1_cdp_status"),
    ("GET",    "/diag",                "handle_v1_cdp_diag"),
    ("GET",    "/raw-info",            "handle_v1_cdp_raw_info"),
    ("GET",    "/test-launch",         "handle_v1_cdp_test_launch"),
    ("GET",    "/test-ws",             "handle_v1_cdp_test_ws"),
    ("POST",   "/connect",             "handle_v1_cdp_connect"),
    ("POST",   "/disconnect",          "handle_v1_cdp_disconnect"),
    ("POST",   "/navigate",            "handle_v1_cdp_navigate"),
    ("GET",    "/screenshot",          "handle_v1_cdp_screenshot"),
    ("GET",    "/dom",                 "handle_v1_cdp_dom"),
    ("POST",   "/eval",                "handle_v1_cdp_eval"),
    ("POST",   "/click",               "handle_v1_cdp_click"),
    ("POST",   "/type",                "handle_v1_cdp_type"),
    ("GET",    "/tabs",                "handle_v1_cdp_tabs"),
    ("POST",   "/tabs/new",            "handle_v1_cdp_tabs_new"),
    ("POST",   "/tabs/close",          "handle_v1_cdp_tabs_close"),
    ("POST",   "/tabs/activate",       "handle_v1_cdp_tabs_activate"),
    ("GET",    "/cookies",             "handle_v1_cdp_cookies_get"),
    ("POST",   "/cookies",             "handle_v1_cdp_cookies_set"),
    ("DELETE", "/cookies",             "handle_v1_cdp_cookies_delete"),
    ("POST",   "/cookies/clear",       "handle_v1_cdp_cookies_clear"),
    ("GET",    "/cookies/profiles",    "handle_v1_cdp_cookies_profiles"),
    ("POST",   "/cookies/profiles",    "handle_v1_cdp_cookies_profiles"),
    ("POST",   "/network/start",       "handle_v1_cdp_network_start"),
    ("POST",   "/network/stop",        "handle_v1_cdp_network_stop"),
    ("GET",    "/network/requests",    "handle_v1_cdp_network_requests"),
    ("GET",    "/network/har",         "handle_v1_cdp_network_har"),
    ("POST",   "/intercept/start",     "handle_v1_cdp_intercept_start"),
    ("POST",   "/intercept/stop",      "handle_v1_cdp_intercept_stop"),
    ("POST",   "/intercept/rule",      "handle_v1_cdp_intercept_rule"),
    ("DELETE", "/intercept/rule",      "handle_v1_cdp_intercept_rule"),
    ("GET",    "/intercept/rules",     "handle_v1_cdp_intercept_rule"),
    ("GET",    "/session/check",       "handle_v1_cdp_session_check"),
    ("POST",   "/stealth/extract",     "handle_v1_cdp_stealth_extract"),
    ("POST",   "/stealth/shot",        "handle_v1_cdp_stealth_shot"),
    ("GET",    "/health",              "handle_v1_cdp_health"),
]
_CDP_PREFIXES = ["/v1/browser/cdp", "/v1/cdp"]


def _cdp_routes() -> list[Route]:
    """Expand _CDP_ENDPOINTS across both canonical prefixes."""
    out: list[Route] = []
    for prefix in _CDP_PREFIXES:
        for method, subpath, handler in _CDP_ENDPOINTS:
            out.append((method, f"{prefix}{subpath}", handler, "cdp", None))
    return out


# ---------------------------------------------------------------------
# Main declarative list. Order preserved from the legacy files so
# route-shadowing behaviour stays identical (aiohttp resolves in
# insertion order for identical method+path).
# ---------------------------------------------------------------------
# ruff: noqa: E501  -- alignment beats formatter noise here.

ROUTES: list[Route] = [
    ('GET'   , '/'                                               , 'handle_index'                               , 'core', None),
    ('GET'   , '/health'                                         , 'handle_health'                              , 'core', None),
    ('GET'   , '/v1/version'                                     , 'handle_v1_version'                          , 'core', None),
    ('GET'   , '/v1/info'                                        , 'handle_v1_info'                             , 'core', None),
    ('GET'   , '/v1/status'                                      , 'handle_v1_status'                           , 'core', None),
    ('GET'   , '/v1/sysinfo'                                     , 'handle_v1_sysinfo'                          , 'core', None),
    ('GET'   , '/v1/capabilities'                                , 'handle_v1_capabilities'                     , 'core', None),
    ('GET'   , '/v1/hardware'                                    , 'handle_v1_hardware'                         , 'core', None),
    ('GET'   , '/v1/hwinfo'                                      , 'handle_v1_hwinfo'                           , 'core', None),
    ('GET'   , '/v1/inventory'                                   , 'handle_v1_inventory'                        , 'core', None),
    ('GET'   , '/v1/inventory/registry'                          , 'handle_v1_inventory_registry'               , 'core', None),
    ('GET'   , '/v1/ps'                                          , 'handle_v1_ps'                               , 'core', None),
    ('GET'   , '/v1/audit'                                       , 'handle_v1_audit'                            , 'core', None),
    ('POST'  , '/v1/exec'                                        , 'handle_v1_exec'                             , 'core', None),
    # v4.2.0: raw-script endpoint (multi-line body, interpreter via header).
    ('POST'  , '/v1/exec/script'                                 , 'handle_v1_exec_script'                      , 'core', None),
    ('POST'  , '/v1/kill'                                        , 'handle_v1_kill'                             , 'core', None),
    ('POST'  , '/v1/upload'                                      , 'handle_v1_upload'                           , 'core', None),
    ('GET'   , '/v1/download'                                    , 'handle_v1_download'                         , 'core', None),
    ('PATCH' , '/v1/fs/edit'                                     , 'handle_v1_fs_edit'                          , 'core', None),
    ('POST'  , '/v1/fs/edit/apply'                               , 'handle_v1_fs_edit_apply'                    , 'core', None),
    ('POST'  , '/v1/fs/edit/rollback'                            , 'handle_v1_fs_edit_rollback'                 , 'core', None),
    ('POST'  , '/v1/fs/view'                                     , 'handle_v1_fs_view'                          , 'core', None),
    ('POST'  , '/v1/fs/create'                                   , 'handle_v1_fs_create'                        , 'core', None),
    ('GET'   , '/v1/memory'                                      , 'handle_v1_memory'                           , 'core', None),
    ('POST'  , '/v1/memory'                                      , 'handle_v1_memory_set'                       , 'core', None),
    ('DELETE', '/v1/memory'                                      , 'handle_v1_memory_delete'                    , 'core', None),
    ('GET'   , '/v1/missions'                                    , 'handle_v1_missions'                         , 'core', None),
    ('POST'  , '/v1/beep'                                        , 'handle_v1_beep'                             , 'core', None),
    ('GET'   , '/v1/doctor'                                      , 'handle_v1_doctor'                           , 'core', None),
    ('GET'   , '/v1/reports'                                     , 'handle_v1_reports'                          , 'core', None),
    ('GET'   , '/v1/browser/search'                              , 'handle_v1_browser_search'                   , 'core', None),
    ('GET'   , '/v1/browser/read'                                , 'handle_v1_browser_read'                     , 'core', None),
    ('GET'   , '/v1/sys/svc'                                     , 'handle_v1_sys_svc'                          , 'core', None),
    ('GET'   , '/v1/service/info'                                , 'handle_v1_service_info'                     , 'core', None),
    ('GET'   , '/v1/sys/funnel'                                  , 'handle_v1_sys_funnel'                       , 'core', None),
    ('POST'  , '/v1/token/regenerate'                            , 'handle_v1_token_regenerate'                 , 'core', None),
    ('POST'  , '/v1/tailscale/funnel/{action}'                   , 'handle_v1_tailscale_funnel'                 , 'core', None),
    ('GET'   , '/v1/tailscale/funnel/{action}'                   , 'handle_v1_tailscale_funnel'                 , 'core', None),
    ('POST'  , '/v1/cloudflared/tunnel/{action}'                 , 'handle_v1_cloudflared_tunnel'               , 'core', None),
    ('GET'   , '/v1/cloudflared/tunnel/{action}'                 , 'handle_v1_cloudflared_tunnel'               , 'core', None),
    ('GET'   , '/v1/zerotier/status'                             , 'handle_v1_zerotier_status'                  , 'core', None),
    ('POST'  , '/v1/zerotier/network/{action}'                   , 'handle_v1_zerotier_network'                 , 'core', None),
    ('GET'   , '/v1/zerotier/network/{action}'                   , 'handle_v1_zerotier_network'                 , 'core', None),
    # v3.96.0: ZeroTier Central management via api.zerotier.com.
    ('GET'   , '/v1/zerotier/central/status'                     , 'handle_v1_zerotier_central_status'          , 'core', None),
    ('GET'   , '/v1/zerotier/central/networks'                   , 'handle_v1_zerotier_central_networks_list'   , 'core', None),
    ('POST'  , '/v1/zerotier/central/networks'                   , 'handle_v1_zerotier_central_networks_create' , 'core', None),
    ('GET'   , '/v1/zerotier/central/networks/{nwid}'            , 'handle_v1_zerotier_central_network_get'     , 'core', None),
    ('DELETE', '/v1/zerotier/central/networks/{nwid}'            , 'handle_v1_zerotier_central_network_delete'  , 'core', None),
    ('GET'   , '/v1/zerotier/central/networks/{nwid}/members'    , 'handle_v1_zerotier_central_members_list'    , 'core', None),
    ('POST'  , '/v1/zerotier/central/networks/{nwid}/members/{node}', 'handle_v1_zerotier_central_member_update' , 'core', None),
    ('DELETE', '/v1/zerotier/central/networks/{nwid}/members/{node}', 'handle_v1_zerotier_central_member_delete' , 'core', None),
    ('GET'   , '/v1/tunnels/status'                              , 'handle_v1_tunnels_status'                   , 'core', None),
    ('GET'   , '/v1/tunnels/active'                              , 'handle_v1_tunnels_active'                   , 'core', None),
    ('POST'  , '/v1/tunnels/start'                               , 'handle_v1_tunnels_start'                    , 'core', None),
    ('POST'  , '/v1/tunnels/stop'                                , 'handle_v1_tunnels_stop'                     , 'core', None),
    # v4.1.0: reachability probe for the active transport.
    ('GET'   , '/v1/tunnels/probe'                               , 'handle_v1_tunnels_probe'                    , 'core', None),
    ('GET'   , '/v1/agent/config'                                , 'handle_v1_agent_config'                     , 'core', None),
    ('GET'   , '/v1/admin/update/status'                         , 'handle_v1_admin_update_status'              , 'core', None),
    ('POST'  , '/v1/admin/update/check'                          , 'handle_v1_admin_update_check'               , 'core', None),
    ('POST'  , '/v1/admin/update/apply'                          , 'handle_v1_admin_update_apply'               , 'core', None),
    ('POST'  , '/v1/admin/update/restart'                        , 'handle_v1_admin_update_restart'             , 'core', None),
    ('GET'   , '/v1/mobile/devices'                              , 'handle_v1_mobile_devices'                   , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/info'                        , 'handle_v1_mobile_info'                      , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/screenshot'                  , 'handle_v1_mobile_screenshot'                , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/tap'                         , 'handle_v1_mobile_tap'                       , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/swipe'                       , 'handle_v1_mobile_swipe'                     , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/type'                        , 'handle_v1_mobile_type'                      , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/key'                         , 'handle_v1_mobile_key'                       , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/key'                         , 'handle_v1_mobile_key'                       , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/shell'                       , 'handle_v1_mobile_shell'                     , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/packages'                    , 'handle_v1_mobile_packages'                  , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/gesture'                     , 'handle_v1_mobile_gesture'                   , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/gesture'                     , 'handle_v1_mobile_gesture'                   , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/ui'                          , 'handle_v1_mobile_ui'                        , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/tap_by'                      , 'handle_v1_mobile_tap_by'                    , 'core', None),
    ('GET'   , '/v1/mobile/helpers/status'                       , 'handle_v1_mobile_helpers_status'            , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/helpers/install'             , 'handle_v1_mobile_helpers_install'           , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/ime'                         , 'handle_v1_mobile_ime_status'                , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/ime/set'                     , 'handle_v1_mobile_ime_set'                   , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/ime/reset'                   , 'handle_v1_mobile_ime_reset'                 , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/paste'                       , 'handle_v1_mobile_paste'                     , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/sensors'                     , 'handle_v1_mobile_sensors'                   , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/scroll'                      , 'handle_v1_mobile_scroll'                    , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/key_combo'                   , 'handle_v1_mobile_key_combo'                 , 'core', None),
    ('POST'  , '/v1/mobile/pair'                                 , 'handle_v1_mobile_pair'                      , 'core', None),
    ('POST'  , '/v1/mobile/connect'                              , 'handle_v1_mobile_connect'                   , 'core', None),
    ('POST'  , '/v1/mobile/disconnect'                           , 'handle_v1_mobile_disconnect'                , 'core', None),
    ('POST'  , '/v1/mobile/apk/prepare'                          , 'handle_v1_mobile_apk_prepare'               , 'core', None),
    ('GET'   , '/v1/mobile/apk/prepare'                          , 'handle_v1_mobile_apk_prepare'               , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/apk/install'                 , 'handle_v1_mobile_apk_install'               , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/batch'                       , 'handle_v1_mobile_batch'                     , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/launch'               , 'handle_v1_mobile_camera_launch'             , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/shutter'              , 'handle_v1_mobile_camera_shutter'            , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/camera/photos'               , 'handle_v1_mobile_camera_photos'             , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/pull'                 , 'handle_v1_mobile_camera_pull'               , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/capture'              , 'handle_v1_mobile_camera_capture'            , 'core', None),
    ('POST'  , '/v1/mobile/apk/upload'                           , 'handle_v1_mobile_apk_upload'                , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/recording/sync'              , 'handle_v1_mobile_record_sync'               , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/recording/start'             , 'handle_v1_mobile_record_start'              , 'core', None),
    ('POST'  , '/v1/mobile/recording/{rec_id}/stop'              , 'handle_v1_mobile_record_stop'               , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/recordings'                  , 'handle_v1_mobile_record_list'               , 'core', None),
    ('GET'   , '/v1/mobile/recording/{rec_id}'                   , 'handle_v1_mobile_record_pull'               , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/recording/purge'             , 'handle_v1_mobile_record_purge'              , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/mirror'                      , 'handle_v1_mobile_mirror_ws'                 , 'core', None),
    ('GET'   , '/v1/mobile/mirror/stats'                         , 'handle_v1_mobile_mirror_stats'              , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/mirror/stop'                 , 'handle_v1_mobile_mirror_stop'               , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/camera/controls'             , 'handle_v1_mobile_camera_controls'           , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/mode'                 , 'handle_v1_mobile_camera_mode'               , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/lens'                 , 'handle_v1_mobile_camera_lens'               , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/zoom'                 , 'handle_v1_mobile_camera_zoom'               , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/flash'                , 'handle_v1_mobile_camera_flash'              , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/record/start'         , 'handle_v1_mobile_camera_record_start'       , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/camera/record/stop'          , 'handle_v1_mobile_camera_record_stop'        , 'core', None),
    ('GET'   , '/v1/mobile/transport'                            , 'handle_v1_mobile_transport_status'          , 'core', None),
    ('GET'   , '/v1/mobile/{serial}/transport'                   , 'handle_v1_mobile_transport_status'          , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/transport/tcp/enable'        , 'handle_v1_mobile_transport_tcp_enable'      , 'core', None),
    ('POST'  , '/v1/mobile/{serial}/transport/tcp/disable'       , 'handle_v1_mobile_transport_tcp_disable'     , 'core', None),
    ('POST'  , '/v1/restart'                                     , 'handle_v1_restart'                          , 'core', None),
    ('GET'   , '/v1/webhooks'                                    , 'handle_v1_webhooks_get'                     , 'core', None),
    ('POST'  , '/v1/webhooks'                                    , 'handle_v1_webhooks_set'                     , 'core', None),
    ('GET'   , '/v1/config'                                      , 'handle_v1_config'                           , 'core', None),
    ('GET'   , '/v1/browser/dump'                                , 'handle_v1_browser_dump'                     , 'core', None),
    ('GET'   , '/v1/browser/fetch'                               , 'handle_v1_browser_fetch'                    , 'core', None),
    ('GET'   , '/v1/browser/head'                                , 'handle_v1_browser_head'                     , 'core', None),
    ('POST'  , '/v1/agents'                                      , 'handle_v1_agents_create'                    , 'core', None),
    ('GET'   , '/v1/agents'                                      , 'handle_v1_agents_list'                      , 'core', None),
    ('GET'   , '/v1/agents/{agent_id}'                           , 'handle_v1_agents_get'                       , 'core', None),
    ('DELETE', '/v1/agents/{agent_id}'                           , 'handle_v1_agents_delete'                    , 'core', None),
    ('GET'   , '/v2/'                                            , 'handle_v2_index'                            , 'compat', None),
    ('GET'   , '/v2/status'                                      , 'handle_v2_status'                           , 'compat', None),
    ('GET'   , '/v2/health'                                      , 'handle_v2_health'                           , 'compat', None),
    ('GET'   , '/v2/browser/status'                              , 'handle_v2_browser_status'                   , 'compat', None),
    ('POST'  , '/v2/exec'                                        , 'handle_v2_exec'                             , 'compat', None),
    ('GET'   , '/v2/deprecations'                                , 'handle_v2_deprecations'                     , 'compat', None),
    ('GET'   , '/v1/tracing'                                     , 'handle_v1_tracing'                          , 'compat', None),
    ('POST'  , '/v1/tracing'                                     , 'handle_v1_tracing'                          , 'compat', None),
    ('GET'   , '/v1/traces/export'                               , 'handle_v1_traces_export'                    , 'compat', None),
    ('POST'  , '/v1/traces/export'                               , 'handle_v1_traces_export'                    , 'compat', None),
    ('GET'   , '/gui'                                            , 'handle_gui'                                 , 'compat', None),
    ('GET'   , '/gui/assets/manifest.json'                       , 'handle_gui_asset_manifest'                  , 'compat', None),
    ('GET'   , '/gui/assets/{path:.*}'                           , 'handle_gui_asset'                           , 'compat', None),
    ('GET'   , '/gui/docs/{path:.*}'                             , 'handle_gui_docs'                            , 'compat', None),
    ('POST'  , '/mcp'                                            , 'handle_mcp_post'                            , 'compat', None),
    ('DELETE', '/mcp'                                            , 'handle_mcp_delete'                          , 'compat', None),
    ('GET'   , '/sse'                                            , 'handle_sse'                                 , 'compat', None),
    ('POST'  , '/messages'                                       , 'handle_sse_messages'                        , 'compat', None),
    ('GET'   , '/ws'                                             , 'handle_ws'                                  , 'compat', None),
    ('GET'   , '/gateway'                                        , 'handle_gateway_index'                       , 'compat', None),
    ('GET'   , '/gateway/tools'                                  , 'handle_gateway_tools'                       , 'compat', None),
    ('POST'  , '/run'                                            , 'handle_gateway_run'                         , 'compat', None),
    ('POST'  , '/tool'                                           , 'handle_gateway_tool'                        , 'compat', None),
    ('GET'   , '/v1/desktop/screenshot'                          , 'handle_v1_desktop_screenshot'               , 'desktop', None),
    ('GET'   , '/v1/desktop/displays'                            , 'handle_v1_desktop_displays'                 , 'desktop', None),
    ('POST'  , '/v1/desktop/click'                               , 'handle_v1_desktop_click'                    , 'desktop', None),
    ('POST'  , '/v1/desktop/type'                                , 'handle_v1_desktop_type'                     , 'desktop', None),
    ('POST'  , '/v1/desktop/key'                                 , 'handle_v1_desktop_key'                      , 'desktop', None),
    ('POST'  , '/v1/desktop/mouse'                               , 'handle_v1_desktop_mouse'                    , 'desktop', None),
    ('GET'   , '/v1/desktop/windows'                             , 'handle_v1_desktop_windows'                  , 'desktop', None),
    ('GET'   , '/v1/desktop/active_window'                       , 'handle_v1_desktop_active_window'            , 'desktop', None),
    ('POST'  , '/v1/desktop/focus'                               , 'handle_v1_desktop_focus'                    , 'desktop', None),
    ('POST'  , '/v1/desktop/window_action'                       , 'handle_v1_desktop_window_action'            , 'desktop', None),
    ('POST'  , '/v1/desktop/resolve_text_target'                 , 'handle_v1_desktop_resolve_text_target'      , 'desktop', None),
    ('POST'  , '/v1/desktop/text_action'                         , 'handle_v1_desktop_text_action'              , 'desktop', None),
    ('POST'  , '/v1/desktop/ocr'                                 , 'handle_v1_desktop_ocr'                      , 'desktop', None),
    ('POST'  , '/v1/desktop/find_text'                           , 'handle_v1_desktop_find_text'                , 'desktop', None),
    ('POST'  , '/v1/desktop/click_text'                          , 'handle_v1_desktop_click_text'               , 'desktop', None),
    ('GET'   , '/v1/control/status'                              , 'handle_v1_control_status'                   , 'desktop', None),
    ('POST'  , '/v1/control/pause'                               , 'handle_v1_control_pause'                    , 'desktop', None),
    ('POST'  , '/v1/control/resume'                              , 'handle_v1_control_resume'                   , 'desktop', None),
    ('POST'  , '/v1/control/revoke'                              , 'handle_v1_control_revoke'                   , 'desktop', None),
    ('GET'   , '/v1/recall'                                      , 'handle_v1_recall'                           , 'domain', None),
    ('GET'   , '/v1/recall/digest'                               , 'handle_v1_recall_digest'                    , 'domain', None),
    ('POST'  , '/v1/plan'                                        , 'handle_v1_plan'                             , 'domain', None),
    ('POST'  , '/v1/react'                                       , 'handle_v1_react'                            , 'domain', None),
    ('POST'  , '/v1/reflect'                                     , 'handle_v1_reflect'                          , 'domain', None),
    ('GET'   , '/v1/audit/stats'                                 , 'handle_v1_audit_stats'                      , 'domain', None),
    ('GET'   , '/v1/tasks'                                       , 'handle_v1_tasks_get'                        , 'domain', None),
    ('POST'  , '/v1/tasks'                                       , 'handle_v1_tasks_post'                       , 'domain', None),
    ('POST'  , '/v1/tasks/clean'                                 , 'handle_v1_tasks_clean'                      , 'domain', None),
    ('GET'   , '/v1/watch/files'                                 , 'handle_v1_watch_files'                      , 'domain', None),
    ('POST'  , '/v1/watch/files'                                 , 'handle_v1_watch_files'                      , 'domain', None),
    ('DELETE', '/v1/watch/files'                                 , 'handle_v1_watch_files'                      , 'domain', None),
    ('GET'   , '/v1/skills'                                      , 'handle_v1_skills'                           , 'domain', None),
    ('POST'  , '/v1/skills/install'                              , 'handle_v1_skills_install'                   , 'domain', None),
    ('POST'  , '/v1/skills/uninstall'                            , 'handle_v1_skills_uninstall'                 , 'domain', None),
    ('POST'  , '/v1/skills/run'                                  , 'handle_v1_skills_run'                       , 'domain', None),
    ('GET'   , '/v1/hooks'                                       , 'handle_v1_hooks'                            , 'domain', None),
    ('GET'   , '/v1/agents'                                      , 'handle_v1_agents'                           , 'domain', None),
    ('GET'   , '/v1/subagents'                                   , 'handle_v1_subagents'                        , 'domain', None),
    ('POST'  , '/v1/subagents/spawn'                             , 'handle_v1_subagents_spawn'                  , 'domain', None),
    ('GET'   , '/v1/mission/show'                                , 'handle_v1_mission_show'                     , 'domain', None),
    ('GET'   , '/v1/mission/status'                              , 'handle_v1_mission_status'                   , 'domain', None),
    ('GET'   , '/v1/mission/report'                              , 'handle_v1_mission_report'                   , 'domain', None),
    ('GET'   , '/v1/mission/history'                             , 'handle_v1_mission_history'                  , 'domain', None),
    ('GET'   , '/v1/mission/lineage'                             , 'handle_v1_mission_lineage'                  , 'domain', None),
    ('GET'   , '/v1/mission/family'                              , 'handle_v1_mission_family'                   , 'domain', None),
    ('GET'   , '/v1/mission/catalog'                             , 'handle_v1_mission_catalog'                  , 'domain', None),
    ('GET'   , '/v1/mission/schedules'                           , 'handle_v1_mission_schedules'                , 'domain', None),
    ('GET'   , '/v1/mission/schedules/state'                     , 'handle_v1_mission_schedules_state'          , 'domain', None),
    ('GET'   , '/v1/mission/templates'                           , 'handle_v1_mission_templates'                , 'domain', None),
    ('POST'  , '/v1/mission/compose'                             , 'handle_v1_mission_compose'                  , 'domain', None),
    ('POST'  , '/v1/mission/propose'                             , 'handle_v1_mission_propose'                  , 'domain', None),
    ('POST'  , '/v1/mission/create'                              , 'handle_v1_mission_create'                   , 'domain', None),
    ('POST'  , '/v1/mission/run'                                 , 'handle_v1_mission_run'                      , 'domain', None),
    ('POST'  , '/v1/mission/rerun'                               , 'handle_v1_mission_rerun'                    , 'domain', None),
    ('POST'  , '/v1/mission/recover'                             , 'handle_v1_mission_recover'                  , 'domain', None),
    ('POST'  , '/v1/mission/followup'                            , 'handle_v1_mission_followup'                 , 'domain', None),
    ('POST'  , '/v1/mission/iterate'                             , 'handle_v1_mission_iterate'                  , 'domain', None),
    ('POST'  , '/v1/mission/schedules'                           , 'handle_v1_mission_schedules'                , 'domain', None),
    ('DELETE', '/v1/mission/schedules'                           , 'handle_v1_mission_schedules'                , 'domain', None),
    ('POST'  , '/v1/mission/schedules/tick'                      , 'handle_v1_mission_schedules_tick'           , 'domain', None),
    ('GET'   , '/v1/extension/policies'                          , 'handle_v1_extension_policies'               , 'domain', None),
    ('GET'   , '/v1/extension/instructions'                      , 'handle_v1_extension_instructions'           , 'domain', None),
    ('POST'  , '/v1/extension/preview'                           , 'handle_v1_extension_preview'                , 'domain', None),
    ('POST'  , '/v1/extension/execute'                           , 'handle_v1_extension_execute'                , 'domain', None),
    ('GET'   , '/v1/metrics'                                     , 'handle_v1_metrics'                          , 'domain', None),
    ('GET'   , '/v1/logs'                                        , 'handle_v1_logs'                             , 'domain', None),
    ('GET'   , '/v1/live-metrics'                                , 'handle_v1_live_metrics'                     , 'domain', None),
    ('GET'   , '/v1/live-metrics/stream'                         , 'handle_v1_live_metrics_stream'              , 'domain', None),
    ('GET'   , '/metrics'                                        , 'handle_prometheus_metrics'                  , 'domain', None),
    ('GET'   , '/api-docs'                                       , 'handle_api_docs'                            , 'domain', None),
    ('GET'   , '/openapi.json'                                   , 'handle_api_docs'                            , 'domain', None),
    ('POST'  , '/v1/browser/browse'                              , 'handle_v1_browser_browse'                   , 'domain', None),
    ('GET'   , '/v1/events'                                      , 'handle_v1_events'                           , 'domain', None),
    ('POST'  , '/v1/skills/reload'                               , 'handle_v1_skills_reload'                    , 'domain', None),
    ('GET'   , '/v1/audit/log'                                   , 'handle_v1_audit_log'                        , 'domain', None),
    ('GET'   , '/v1/watchdog'                                    , 'handle_v1_watchdog'                         , 'domain', None),
    ('POST'  , '/v1/watchdog'                                    , 'handle_v1_watchdog'                         , 'domain', None),
    ('GET'   , '/v1/users'                                       , 'handle_v1_users'                            , 'domain', None),
    ('POST'  , '/v1/users'                                       , 'handle_v1_users'                            , 'domain', None),
    ('DELETE', '/v1/users'                                       , 'handle_v1_users'                            , 'domain', None),
    ('POST'  , '/v1/batch'                                       , 'handle_v1_batch'                            , 'domain', None),
    ('GET'   , '/v1/profiles'                                    , 'handle_v1_profiles'                         , 'domain', None),
    ('POST'  , '/v1/profiles'                                    , 'handle_v1_profiles'                         , 'domain', None),
    ('POST'  , '/v1/profiles/{name}/load'                        , 'handle_v1_profiles_load'                    , 'domain', None),
    ('GET'   , '/v1/alerts'                                      , 'handle_v1_alerts'                           , 'domain', None),
    ('POST'  , '/v1/alerts'                                      , 'handle_v1_alerts'                           , 'domain', None),
    ('GET'   , '/v1/tls'                                         , 'handle_v1_tls'                              , 'domain', None),
    ('POST'  , '/v1/tls'                                         , 'handle_v1_tls'                              , 'domain', None),
    ('GET'   , '/v1/grpc'                                        , 'handle_v1_grpc'                             , 'domain', None),
    ('POST'  , '/v1/grpc'                                        , 'handle_v1_grpc'                             , 'domain', None),
    ('GET'   , '/gui/v2'                                         , 'handle_gui_v2'                              , 'domain', None),
    ('GET'   , '/v1/ratelimit'                                   , 'handle_v1_ratelimit'                        , 'domain', None),
    ('POST'  , '/v1/ratelimit'                                   , 'handle_v1_ratelimit'                        , 'domain', None),
    ('GET'   , '/v1/sandbox'                                     , 'handle_v1_sandbox'                          , 'domain', None),
    ('POST'  , '/v1/sandbox'                                     , 'handle_v1_sandbox'                          , 'domain', None),
    ('GET'   , '/v1/cluster'                                     , 'handle_v1_cluster'                          , 'domain', None),
    ('POST'  , '/v1/cluster'                                     , 'handle_v1_cluster'                          , 'domain', None),
]




# CDP routes are always expanded from the compact source table.
_CDP_EXPANDED = _cdp_routes()


def all_routes() -> list[Route]:
    """The full effective route table: hand-declared + imported
    legacy + CDP expansion."""
    return list(ROUTES) + _CDP_EXPANDED


# ---------------------------------------------------------------------
# Application-facing registration.
# ---------------------------------------------------------------------

def _add(app: web.Application, method: str, path: str, handler: Callable) -> None:
    app.router.add_route(method, path, handler)


def register_group(
    app: web.Application,
    h: Mapping[str, Callable],
    group: str,
    *,
    strict: bool = False,
) -> int:
    """Register every route whose group matches. Returns count.

    ``strict=True`` raises ``KeyError`` when a handler name is missing
    from ``h``; the default is ``False`` (skip silently) so shims can
    be loaded independently even when not every subsystem is wired
    up yet.
    """
    count = 0
    for method, path, handler_name, grp, _opts in all_routes():
        if grp != group:
            continue
        if handler_name not in h:
            if strict:
                raise KeyError(handler_name)
            continue
        _add(app, method, path, h[handler_name])
        count += 1
    return count


def register_all(
    app: web.Application,
    h: Mapping[str, Callable],
) -> int:
    """Register every route regardless of group. Convenience for
    callers that already assemble the full handler dict."""
    count = 0
    for method, path, handler_name, _grp, _opts in all_routes():
        if handler_name in h:
            _add(app, method, path, h[handler_name])
            count += 1
    return count
