"""CDP browser CLI component."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.browser import CDPBrowser
from arena.browser.cdp_client.process import launch_browser
from arena.browser.cdp_client.sync_browser import SyncCDPBrowser
from arena.browser.cdp_client.tab_manager import CDPTabManager
from arena.browser.cdp_client.tabs_http import list_tabs

async def _multitab_demo():
    """Interactive multi-tab management demo using CDPTabManager."""
    print("=" * 60)
    print("  CDP Multi-Tab Manager Demo")
    print("=" * 60)

    async with CDPTabManager(headless=True) as mgr:
        print(f"\n[Manager] Connected. Tabs tracked: {mgr.tab_count}")

        # Create 3 tabs with different URLs
        urls = [
            "https://example.com",
            "https://httpbin.org/html",
            "https://www.wikipedia.org",
        ]

        tabs = []
        for url in urls:
            try:
                tab = await mgr.new_tab(url)
                tabs.append(tab)
                print(f"  [+] Tab created: {tab.target_id[:12]}... → {url}")
            except Exception as e:
                print(f"  [!] Failed to create tab for {url}: {e}")

        # List all tabs
        print(f"\n[Manager] {mgr.tab_count} tabs:")
        for i, tab in enumerate(mgr.list_tabs()):
            marker = " *" if tab.target_id == mgr.active_tab_id else "  "
            conn = "●" if tab.connected else "○"
            print(f"  {marker}[{i}] {conn} {tab.target_id[:12]}... | {tab.title[:40] or '(no title)'} | {tab.url[:50]}")

        # Take screenshot of active tab
        active = mgr.active_tab
        if active:
            print(f"\n[Active Tab] Taking screenshot...")
            try:
                await active.screenshot("multitab_active.png")
                print(f"  [OK] Screenshot saved: multitab_active.png")
            except Exception as e:
                print(f"  [!] Screenshot failed: {e}")

            # Get title
            try:
                title = await active.get_title()
                print(f"  [Title] {title}")
            except Exception:
                pass

        # Switch active tab
        if len(tabs) > 1:
            second_tab = tabs[1]
            mgr.activate(second_tab.target_id)
            print(f"\n[Manager] Switched active tab to: {second_tab.target_id[:12]}...")

            # Navigate the newly active tab
            try:
                await second_tab.navigate("https://example.org")
                print(f"  [OK] Navigated to example.org")
                title = await second_tab.get_title()
                print(f"  [Title] {title}")
            except Exception as e:
                print(f"  [!] Navigation failed: {e}")

        # Close the first tab
        if tabs:
            first_id = tabs[0].target_id
            success = await mgr.close_tab(first_id)
            print(f"\n[Manager] Closed tab {first_id[:12]}...: {'OK' if success else 'FAILED'}")
            print(f"  Remaining tabs: {mgr.tab_count}")

        # Final sync
        final_tabs = await mgr.sync_tabs()
        print(f"\n[Manager] Final tab count: {len(final_tabs)}")

    print("\n[Manager] Demo complete. Browser closed.")
