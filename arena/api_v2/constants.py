"""API v2 constants and deprecation metadata."""
from __future__ import annotations

DEPRECATED_ENDPOINTS: dict[str, dict[str, str]] = {
    "/v1/service/info": {"deprecated_since": "1.9.27", "replacement": "/v1/status", "removal_version": "2.3.0"},
    "/v1/sys/svc": {"deprecated_since": "1.9.27", "replacement": "/v1/status", "removal_version": "2.3.0"},
    "/v1/sys/funnel": {"deprecated_since": "1.9.27", "replacement": "/v1/tailscale/funnel/status", "removal_version": "2.3.0"},
}

V2_ENDPOINTS: dict[str, str] = {
    "GET /v2/": "API v2 index",
    "GET /v2/status": "Bridge status (replaces /v1/status)",
    "GET /v2/health": "Detailed health check",
    "GET /v2/browser/status": "CDP + browser status combined",
    "POST /v2/exec": "Exec with sandbox by default",
    "GET /v2/deprecations": "List deprecated v1 endpoints",
}

MIGRATION_GUIDE: dict[str, str] = {
    "/v1/service/info → /v1/status": "Use /v1/status for all service information",
    "/v1/sys/svc → /v1/status": "Service status is now part of /v1/status",
    "/v1/sys/funnel → /v1/tailscale/funnel/status": "Funnel status moved to tailscale namespace",
}
