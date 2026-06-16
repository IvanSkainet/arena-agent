"""CDP network monitor components."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403

class NetworkRequest:
    """Represents a single network request/response cycle.

    Accumulates data as CDP events arrive:
      requestWillBeSent → responseReceived → loadingFinished / loadingFailed
    """

    __slots__ = (
        "request_id", "url", "method", "headers", "post_data",
        "resource_type", "frame_id", "timestamp", "wall_time",
        "redirect_count", "redirect_response", "initiator",
        "response_status", "response_status_text", "response_headers",
        "response_mimeType", "response_remote_ip", "response_remote_port",
        "response_protocol", "response_security_details",
        "encoded_data_length", "decoded_body_length",
        "error_text", "error_canceled", "error_blocked_reason",
        "finished", "finish_time",
    )

    def __init__(self, request_id: str, **kwargs):
        self.request_id = request_id
        self.url = kwargs.get("url", "")
        self.method = kwargs.get("method", "")
        self.headers = kwargs.get("headers", {})
        self.post_data = kwargs.get("postData")
        self.resource_type = kwargs.get("resourceType", "")
        self.frame_id = kwargs.get("frameId", "")
        self.timestamp = kwargs.get("timestamp", 0)
        self.wall_time = kwargs.get("wallTime", 0)
        self.redirect_count = kwargs.get("redirectCount", 0)
        self.redirect_response = kwargs.get("redirectResponse")
        self.initiator = kwargs.get("initiator", {})
        # Response fields (filled later)
        self.response_status = None
        self.response_status_text = None
        self.response_headers = None
        self.response_mimeType = None
        self.response_remote_ip = None
        self.response_remote_port = None
        self.response_protocol = None
        self.response_security_details = None
        self.encoded_data_length = None
        self.decoded_body_length = None
        # Error fields
        self.error_text = None
        self.error_canceled = False
        self.error_blocked_reason = None
        # State
        self.finished = False
        self.finish_time = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict (for API responses / logging)."""
        return {k: getattr(self, k) for k in self.__slots__ if getattr(self, k) is not None}
