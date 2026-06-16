"""Browser-level WebSocket mixins for CDPTabManager."""
from __future__ import annotations

from arena.browser.cdp_client.tab_manager_browser_connect import CDPTabManagerBrowserConnectMixin
from arena.browser.cdp_client.tab_manager_browser_events import CDPTabManagerBrowserEventsMixin


class CDPTabManagerBrowserWsMixin(CDPTabManagerBrowserConnectMixin, CDPTabManagerBrowserEventsMixin):
    """Combined browser-level WebSocket behavior."""
