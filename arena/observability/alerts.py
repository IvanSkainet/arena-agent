"""Prometheus-style alert configuration and status handler."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.handler_context import AlertsHandlerContext

ALERTS_CONFIG: dict[str, dict[str, Any]] = {
    "bridge_down": {"enabled": True, "threshold_seconds": 30, "description": "Bridge unresponsive for >30s"},
    "high_latency": {"enabled": True, "threshold_seconds": 5.0, "description": "Request latency >5s"},
    "memory_leak": {"enabled": True, "threshold_mb": 512, "description": "Memory usage >512MB"},
    "cdp_disconnect": {"enabled": True, "threshold_reconnects": 5, "description": "More than 5 CDP reconnects"},
    "error_rate": {"enabled": True, "threshold_percent": 10.0, "description": "Error rate >10%"},
    "rate_limit": {"enabled": True, "threshold_percent": 80.0, "description": "Rate limit >80% utilized"},
}


@dataclass(frozen=True)
class AlertHandlers:
    alerts: object


def make_alert_handlers(ctx: AlertsHandlerContext) -> AlertHandlers:
    async def handle_v1_alerts(request: web.Request) -> web.Response:
        """GET /v1/alerts — List alert configurations and current status.
        POST /v1/alerts — Update alert configuration.
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        if request.method == "POST":
            try:
                data = await request.json()
                for alert_name, config in data.items():
                    if alert_name in ALERTS_CONFIG and isinstance(config, dict):
                        for k, v in config.items():
                            if k in ALERTS_CONFIG[alert_name]:
                                ALERTS_CONFIG[alert_name][k] = v
                ctx.log_info("[Alerts] Configuration updated")
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

        # Compute current alert states.
        alert_states: dict[str, dict[str, Any]] = {}
        uptime = ctx.now() - ctx.metrics["start_time"]
        total_reqs = ctx.metrics["total_requests"]
        total_errors = ctx.metrics["total_errors"]

        alert_states["bridge_down"] = {"status": "OK", "uptime_s": round(uptime, 1)}

        # High latency check.
        durations = ctx.metrics.get("request_durations", [])
        avg_dur = sum(durations[-100:]) / len(durations[-100:]) if durations else 0
        alert_states["high_latency"] = {
            "status": "FIRING" if avg_dur > ALERTS_CONFIG["high_latency"]["threshold_seconds"] else "OK",
            "avg_duration_s": round(avg_dur, 3),
            "threshold_s": ALERTS_CONFIG["high_latency"]["threshold_seconds"],
        }

        # Memory check.
        alert_states["memory_leak"] = {
            "status": "FIRING" if ctx.watchdog_state["memory_mb"] > ALERTS_CONFIG["memory_leak"]["threshold_mb"] else "OK",
            "current_mb": ctx.watchdog_state["memory_mb"],
            "threshold_mb": ALERTS_CONFIG["memory_leak"]["threshold_mb"],
        }

        # CDP disconnect check.
        reconnects = ctx.cdp_state.get("reconnect_count", 0)
        alert_states["cdp_disconnect"] = {
            "status": "FIRING" if reconnects > ALERTS_CONFIG["cdp_disconnect"]["threshold_reconnects"] else "OK",
            "reconnects": reconnects,
            "threshold": ALERTS_CONFIG["cdp_disconnect"]["threshold_reconnects"],
        }

        # Error rate check.
        error_rate = (total_errors / total_reqs * 100) if total_reqs > 0 else 0
        alert_states["error_rate"] = {
            "status": "FIRING" if error_rate > ALERTS_CONFIG["error_rate"]["threshold_percent"] else "OK",
            "error_rate_pct": round(error_rate, 2),
            "threshold_pct": ALERTS_CONFIG["error_rate"]["threshold_percent"],
        }

        # Rate limit utilization.
        rl_usage = 0.0
        with ctx.rate_limit_lock:
            for timestamps in ctx.rate_limit_store.values():
                now = ctx.now()
                recent = [t for t in timestamps if now - t < ctx.rate_limit_window]
                if recent:
                    rl_usage = max(rl_usage, len(recent) / ctx.rate_limit_max * 100)
        alert_states["rate_limit"] = {
            "status": "FIRING" if rl_usage > ALERTS_CONFIG["rate_limit"]["threshold_percent"] else "OK",
            "usage_pct": round(rl_usage, 1),
            "threshold_pct": ALERTS_CONFIG["rate_limit"]["threshold_percent"],
        }

        firing = sum(1 for s in alert_states.values() if s.get("status") == "FIRING")

        return ctx.cors_json_response({
            "ok": True,
            "alerts": ALERTS_CONFIG,
            "states": alert_states,
            "firing": firing,
            "healthy": firing == 0,
        })

    return AlertHandlers(alerts=handle_v1_alerts)
