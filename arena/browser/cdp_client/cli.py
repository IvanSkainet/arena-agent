"""CLI for cdp_browser compatibility wrapper."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.browser import CDPBrowser
from cdp_browser_modules.process import launch_browser
from cdp_browser_modules.sync_browser import SyncCDPBrowser
from cdp_browser_modules.tab_manager import CDPTabManager
from cdp_browser_modules.tabs_http import list_tabs

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

def main():
    """Synchronous CLI — works without aiohttp."""
    if len(sys.argv) < 2:
        print("Usage: python3 cdp_browser.py <command> [args...]")
        print("Commands:")
        print("  navigate <url>      Open browser and navigate to URL")
        print("  shot [png_path]     Capture screenshot of active page")
        print("  dump                Dump active page outerHTML")
        print("  eval <js>           Evaluate JavaScript in page context")
        print("  tabs                List open browser tabs")
        print("  new <url>           Open a new tab with URL")
        print("  multitab            Interactive multi-tab management demo (async)")
        print("  close <tab_id>      Close a tab by ID")
        print("  activate <tab_id>   Activate a tab by ID")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    logging.basicConfig(level=logging.INFO, format="[CDP] %(message)s")

    if cmd == "tabs":
        tabs = list_tabs()
        if tabs:
            for i, t in enumerate(tabs):
                print(f"  [{i}] {t.get('title', '(no title)')} — {t.get('url', '')}")
        else:
            print("No tabs found. Is the browser running with --remote-debugging-port?")
        return

    if cmd == "new":
        url = sys.argv[2] if len(sys.argv) > 2 else "about:blank"
        ws = get_new_tab_url()
        if ws:
            print(f"[OK] New tab opened. WebSocket: {ws}")
        else:
            print("[ERROR] Failed to open new tab.")
        return

    if cmd == "close":
        if len(sys.argv) < 3:
            print("Provide tab ID to close")
            sys.exit(1)
        tab_id = sys.argv[2]
        if close_tab(tab_id):
            print(f"[OK] Tab {tab_id} closed.")
        else:
            print(f"[ERROR] Failed to close tab {tab_id}.")
        return

    if cmd == "activate":
        if len(sys.argv) < 3:
            print("Provide tab ID to activate")
            sys.exit(1)
        # Activation requires async — use HTTP /json/activate endpoint
        tab_id = sys.argv[2]
        try:
            url = f"http://127.0.0.1:{DEFAULT_PORT}/json/activate/{tab_id}"
            with urllib.request.urlopen(url, timeout=5) as r:
                result = r.read().decode().strip()
                if result == "Target activated":
                    print(f"[OK] Tab {tab_id} activated.")
                else:
                    print(f"[?] Unexpected response: {result}")
        except Exception as e:
            print(f"[ERROR] Failed to activate tab: {e}")
        return

    if cmd == "multitab":
        if not HAS_AIOHTTP:
            print("[ERROR] multitab command requires aiohttp. Install with: pip install aiohttp")
            sys.exit(1)
        asyncio.run(_multitab_demo())
        return

    # All other commands need an active CDP connection
    with SyncCDPBrowser() as browser:
        if cmd == "navigate":
            if len(sys.argv) < 3:
                print("Provide a URL")
                sys.exit(1)
            url = sys.argv[2]
            print(f"[CDP] Navigating to {url}...")
            browser.navigate(url)
            print("[OK] Navigation completed.")

        elif cmd == "shot":
            path = sys.argv[2] if len(sys.argv) > 2 else "screenshot_cdp.png"
            print(f"[CDP] Capturing screenshot to {path}...")
            if browser.screenshot(path):
                print(f"[OK] Screenshot written to {path} ({os.path.getsize(path)} bytes)")
            else:
                print("[ERROR] Failed to capture screenshot.")

        elif cmd == "dump":
            print("[CDP] Dumping DOM (outerHTML)...")
            html = browser.dump_dom()
            if html:
                print(html)
            else:
                print("[ERROR] Failed to dump DOM.")

        elif cmd == "eval":
            if len(sys.argv) < 3:
                print("Provide JS expression")
                sys.exit(1)
            expr = " ".join(sys.argv[2:])
            print(f"[CDP] Evaluating: {expr}")
            result = browser.eval_js(expr)
            if result:
                print(result)
            else:
                print("[ERROR] Failed to evaluate.")

        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)

