"""High-level CDP network interceptor."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.intercept_rule import InterceptRule
from cdp_browser_modules.intercept_rules import CDPNetworkInterceptRulesMixin
from cdp_browser_modules.intercept_runtime import CDPNetworkInterceptRuntimeMixin


class CDPNetworkInterceptor(CDPNetworkInterceptRuntimeMixin, CDPNetworkInterceptRulesMixin):
    """Request interception helper for CDP Network/Fetch domains."""
    def __init__(self, browser: CDPBrowser):
        self._browser = browser
        self._rules: List[InterceptRule] = []
        self._active = False
        self._paused_requests: Dict[str, Dict] = {}  # requestId → paused event params
        self._handler_tasks: set = set()  # Track in-flight handler tasks
