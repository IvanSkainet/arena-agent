"""CDP network monitor components."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403

class CDPNetworkHarMixin:
    def export_har(self) -> Dict[str, Any]:
        """Export recorded requests in HAR-like format.

        Returns:
            Dict in HAR 1.2-like structure for interoperability.
        """
        entries = []
        for req in self._finished:
            # Convert wall_time (epoch float) to ISO 8601
            started_dt = ""
            if req.wall_time:
                from datetime import datetime, timezone
                try:
                    started_dt = datetime.fromtimestamp(req.wall_time, tz=timezone.utc).isoformat()
                except Exception:
                    started_dt = str(req.wall_time)

            # Compute elapsed time in milliseconds
            elapsed_ms = 0
            if req.finish_time is not None and req.timestamp:
                elapsed_ms = round((req.finish_time - req.timestamp) * 1000)

            entry = {
                "startedDateTime": started_dt,
                "request": {
                    "method": req.method,
                    "url": req.url,
                    "headers": req.headers,
                },
                "response": {
                    "status": req.response_status,
                    "statusText": req.response_status_text,
                    "headers": req.response_headers,
                    "mimeType": req.response_mimeType,
                    "remoteIP": req.response_remote_ip,
                    "remotePort": req.response_remote_port,
                },
                "time": elapsed_ms,
            }
            if req.error_text:
                entry["_error"] = req.error_text
            entries.append(entry)

        return {
            "log": {
                "version": "1.2",
                "creator": {"name": "cdp_browser", "version": "1.0"},
                "entries": entries,
            }
        }
