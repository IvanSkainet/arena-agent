"""High-level CDP network monitor."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.network_har import CDPNetworkHarMixin
from cdp_browser_modules.network_request import NetworkRequest


class CDPNetworkMonitor(CDPNetworkHarMixin):
    """Track CDP Network events and request lifecycle."""
    def __init__(self, browser: CDPBrowser, max_entries: int = 1000):
        self._browser = browser
        self._max_entries = max_entries
        self._requests: Dict[str, NetworkRequest] = {}
        self._finished: List[NetworkRequest] = []
        self._active = False

    async def start(self) -> None:
        """Enable network monitoring and register event handlers."""
        if self._active:
            return
        await self._browser.send("Network.enable")
        self._browser.on("Network.requestWillBeSent", self._on_request_will_be_sent)
        self._browser.on("Network.responseReceived", self._on_response_received)
        self._browser.on("Network.loadingFinished", self._on_loading_finished)
        self._browser.on("Network.loadingFailed", self._on_loading_failed)
        self._active = True
        logger.info("[CDPNetworkMonitor] Monitoring started")

    async def stop(self) -> None:
        """Disable network monitoring and unregister event handlers."""
        if not self._active:
            return
        self._browser.off("Network.requestWillBeSent", self._on_request_will_be_sent)
        self._browser.off("Network.responseReceived", self._on_response_received)
        self._browser.off("Network.loadingFinished", self._on_loading_finished)
        self._browser.off("Network.loadingFailed", self._on_loading_failed)
        # Note: We do NOT call Network.disable here because other consumers
        # (e.g., CDPBrowser.get_cookies) may still need the Network domain.
        # Handlers are unregistered so we stop receiving events.
        self._active = False
        logger.info("[CDPNetworkMonitor] Monitoring stopped")

    def active(self) -> bool:
        """Whether monitoring is currently active."""
        return self._active

    def _on_request_will_be_sent(self, params: Dict) -> None:
        """Handle Network.requestWillBeSent."""
        request_id = params.get("requestId", "")
        request_data = params.get("request", {})
        # If this is a redirect, finalize the previous request
        redirect_response = params.get("redirectResponse")
        if redirect_response and request_id in self._requests:
            prev = self._requests[request_id]
            prev.response_status = redirect_response.get("status")
            prev.response_status_text = redirect_response.get("statusText", "")
            prev.response_headers = redirect_response.get("headers", {})
            prev.response_mimeType = redirect_response.get("mimeType", "")
            prev.redirect_count += 1
            self._finalize_request(request_id, params.get("timestamp"))

        # Create new request entry (redirect_response belongs to prev hop, not this one)
        req = NetworkRequest(
            request_id=request_id,
            url=request_data.get("url", ""),
            method=request_data.get("method", ""),
            headers=request_data.get("headers", {}),
            postData=request_data.get("postData"),
            resourceType=params.get("type", ""),
            frameId=params.get("frameId", ""),
            timestamp=params.get("timestamp", 0),
            wallTime=params.get("wallTime", 0),
            redirectCount=0,
            redirectResponse=None,
            initiator=params.get("initiator", {}),
        )
        self._requests[request_id] = req

    def _on_response_received(self, params: Dict) -> None:
        """Handle Network.responseReceived."""
        request_id = params.get("requestId", "")
        response = params.get("response", {})
        req = self._requests.get(request_id)
        if req:
            req.response_status = response.get("status")
            req.response_status_text = response.get("statusText", "")
            req.response_headers = response.get("headers", {})
            req.response_mimeType = response.get("mimeType", "")
            req.response_remote_ip = response.get("remoteIPAddress")
            req.response_remote_port = response.get("remotePort")
            req.response_protocol = response.get("protocol", "")
            req.response_security_details = response.get("securityDetails")

    def _on_loading_finished(self, params: Dict) -> None:
        """Handle Network.loadingFinished."""
        request_id = params.get("requestId", "")
        req = self._requests.get(request_id)
        if req:
            req.encoded_data_length = params.get("encodedDataLength")
            ddl = params.get("decodedDataLength")
            req.decoded_body_length = ddl if ddl is not None else params.get("encodedDataLength")
            self._finalize_request(request_id, params.get("timestamp"))

    def _on_loading_failed(self, params: Dict) -> None:
        """Handle Network.loadingFailed."""
        request_id = params.get("requestId", "")
        req = self._requests.get(request_id)
        if req:
            req.error_text = params.get("errorText", "")
            req.error_canceled = params.get("canceled", False)
            req.error_blocked_reason = params.get("blockedReason")
            self._finalize_request(request_id, params.get("timestamp"))

    def _finalize_request(self, request_id: str, finish_timestamp: float = None) -> None:
        """Move a request from active to finished list."""
        req = self._requests.pop(request_id, None)
        if req:
            req.finished = True
            req.finish_time = finish_timestamp if finish_timestamp is not None else req.timestamp
            self._finished.append(req)
            # Trim if over max
            while len(self._finished) > self._max_entries:
                self._finished.pop(0)

    def get_requests(self, url_filter: Optional[str] = None,
                     resource_type: Optional[str] = None) -> List[NetworkRequest]:
        """Get finished requests, optionally filtered.

        Args:
            url_filter: Only return requests whose URL contains this substring
            resource_type: Only return requests of this resource type (e.g., "Document", "Script")

        Returns:
            List of matching NetworkRequest objects
        """
        results = self._finished
        if url_filter:
            results = [r for r in results if url_filter in r.url]
        if resource_type:
            results = [r for r in results if r.resource_type == resource_type]
        return results

    def get_active_requests(self) -> List[NetworkRequest]:
        """Get currently in-flight requests."""
        return list(self._requests.values())

    def get_request_by_id(self, request_id: str) -> Optional[NetworkRequest]:
        """Get a specific request by its ID."""
        return self._requests.get(request_id) or next(
            (r for r in self._finished if r.request_id == request_id), None
        )

    def total_requests(self) -> int:
        """Total number of finished requests."""
        return len(self._finished)

    def active_count(self) -> int:
        """Number of currently in-flight requests."""
        return len(self._requests)

    def clear(self) -> None:
        """Clear all recorded requests."""
        self._requests.clear()
        self._finished.clear()
