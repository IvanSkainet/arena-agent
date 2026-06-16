"""Tab operation mixins for CDPTabManager."""
from __future__ import annotations

from arena.browser.cdp_client.tab_manager_tab_lifecycle import CDPTabManagerTabLifecycleMixin
from arena.browser.cdp_client.tab_manager_tab_lookup import CDPTabManagerTabLookupMixin


class CDPTabManagerOpsMixin(CDPTabManagerTabLifecycleMixin, CDPTabManagerTabLookupMixin):
    """Combined tab operations."""
