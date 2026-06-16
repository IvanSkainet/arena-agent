"""CDP network interception components."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403

class InterceptRule:
    """A single interception rule for CDPNetworkInterceptor.

    Matches requests by URL pattern and/or resource type,
    and applies an action: block, redirect, modify headers, or mock response.
    """

    def __init__(
        self,
        name: str = "",
        url_pattern: Optional[str] = None,
        resource_type: Optional[str] = None,
        action: str = "block",  # block, redirect, modify_headers, mock
        redirect_url: Optional[str] = None,
        modify_request_headers: Optional[Dict[str, str]] = None,
        modify_response_headers: Optional[Dict[str, str]] = None,
        remove_request_headers: Optional[List[str]] = None,
        remove_response_headers: Optional[List[str]] = None,
        mock_status: int = 200,
        mock_headers: Optional[Dict[str, str]] = None,
        mock_body: Optional[str] = None,
        mock_content_type: str = "text/plain",
        enabled: bool = True,
    ):
        self.name = name
        self.url_pattern = url_pattern
        self.resource_type = resource_type
        if action not in ("block", "redirect", "modify_headers", "mock"):
            raise ValueError(f"Invalid action {action!r}. Must be one of: block, redirect, modify_headers, mock")
        self.action = action
        self.redirect_url = redirect_url
        self.modify_request_headers = modify_request_headers or {}
        self.modify_response_headers = modify_response_headers or {}
        self.remove_request_headers = remove_request_headers or []
        self.remove_response_headers = remove_response_headers or []
        self.mock_status = mock_status
        self.mock_headers = {"Content-Type": mock_content_type}
        if mock_headers:
            self.mock_headers.update(mock_headers)
        self.mock_body = mock_body
        self.enabled = enabled
        self._hit_count = 0

    def matches(self, url: str, resource_type: str) -> bool:
        """Check if this rule matches the given request."""
        if not self.enabled:
            return False
        if self.url_pattern and self.url_pattern not in url:
            return False
        if self.resource_type and self.resource_type != resource_type:
            return False
        return True

    def record_hit(self) -> None:
        """Record that this rule matched a request."""
        self._hit_count += 1

    @property
    def hit_count(self) -> int:
        """Number of times this rule has been triggered."""
        return self._hit_count

    def to_dict(self) -> Dict[str, Any]:
        """Serialize rule to a dict."""
        return {
            "name": self.name,
            "url_pattern": self.url_pattern,
            "resource_type": self.resource_type,
            "action": self.action,
            "enabled": self.enabled,
            "hit_count": self._hit_count,
        }
