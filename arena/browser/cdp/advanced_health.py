"""CDP advanced health handler."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from arena.browser.cdp.advanced_common import get_active_browser
from arena.handler_context import CdpAdvancedHandlerContext
from arena.handler_helpers import authed, err_json


def make_cdp_health_handler(ctx: CdpAdvancedHandlerContext):
    @authed(ctx)
    async def handle_v1_cdp_health(request):
        """GET /v1/browser/cdp/health — CDP connection health dashboard.

        Returns comprehensive health info including:
        - Connection status and uptime
        - Browser process status
        - WebSocket health
        - Reconnect history
        - Active tab info
        - Memory/resource usage
        """

        mgr = ctx.cdp_state.get("manager")
        connected = ctx.cdp_state["connected"]

        health = {
            "ok": True,
            "connected": connected,
            "port": ctx.cdp_state["port"],
            "headless": ctx.cdp_state["headless"],
            "watcher_active": ctx.watcher_active(),
            "reconnect_count": ctx.cdp_state.get("reconnect_count", 0),
            "last_connect_time": ctx.cdp_state.get("last_connect_time"),
            "last_disconnect_reason": ctx.cdp_state.get("last_disconnect_reason"),
            "bridge_uptime_s": round(time.time() - ctx.bridge_start_time),
        }

        if connected and mgr:
            # Browser process info
            if mgr._browser_proc:
                proc = mgr._browser_proc
                health["browser"] = {
                    "pid": proc.pid,
                    "alive": proc.poll() is None,
                    "returncode": proc.returncode,
                }
            else:
                health["browser"] = {"alive": False, "note": "External browser (not launched by bridge)"}

            # Tab info
            tabs = mgr.list_tabs()
            health["tabs"] = {
                "count": len(tabs),
                "active_id": mgr.active_tab_id,
                "details": [t.to_dict() for t in tabs[:10]],
            }

            # Active tab health probe
            if mgr.active_tab and mgr.active_tab.connected:
                health["active_tab"] = {
                    "connected": True,
                    "target_id": mgr.active_tab.target_id,
                    "url": mgr.active_tab.url,
                    "title": mgr.active_tab.title,
                }
                # Quick health check — can we evaluate JS?
                try:
                    result = await asyncio.wait_for(mgr.active_tab.eval_js("1+1"), timeout=3)
                    health["active_tab"]["health_probe"] = "ok" if result == 2 else f"unexpected result: {result}"
                except asyncio.TimeoutError:
                    health["active_tab"]["health_probe"] = "timeout"
                except ConnectionError:
                    health["active_tab"]["health_probe"] = "disconnected"
                except Exception as e:
                    health["active_tab"]["health_probe"] = f"error: {type(e).__name__}"
            else:
                health["active_tab"] = {"connected": False}

            # Connection uptime
            if ctx.cdp_state.get("last_connect_time"):
                try:
                    last = datetime.fromisoformat(ctx.cdp_state["last_connect_time"])
                    uptime = (datetime.now(timezone.utc) - last).total_seconds()
                    health["connection_uptime_s"] = round(uptime)
                except Exception:
                    pass

        else:
            health["browser"] = {"alive": False}
            health["tabs"] = {"count": 0}
            health["active_tab"] = {"connected": False}

        # System resource usage
        try:
            import resource as _resource
            usage = _resource.getrusage(_resource.RUSAGE_SELF)
            health["resources"] = {
                "max_rss_mb": round(usage.ru_maxrss / 1024, 1),
                "user_cpu_s": round(usage.ru_utime, 1),
                "sys_cpu_s": round(usage.ru_stime, 1),
            }
        except Exception:
            pass

        return ctx.cors_json_response(health)


    return handle_v1_cdp_health
