"""CDP browser CLI component."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.browser import CDPBrowser
from arena.browser.cdp_client.process import launch_browser
from arena.browser.cdp_client.sync_browser import SyncCDPBrowser
from arena.browser.cdp_client.tab_manager import CDPTabManager
from arena.browser.cdp_client.tabs_http import list_tabs

from arena.browser.cdp_client.cli_demo import _multitab_demo

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
