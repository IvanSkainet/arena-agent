"""
Chrome DevTools Protocol (CDP) browser controller.

Async-first design using aiohttp for WebSocket communication.
Falls back to synchronous CLI when run as __main__.

Features:
  - Incremental request IDs (no collisions)
  - Event system with callbacks and event queue
  - Page load detection via Page.loadEventFired (no blind sleep)
  - Timeouts on all operations via asyncio.wait_for
  - Auto-reconnect on WebSocket drop
  - Multi-tab awareness (list tabs, connect to specific tab)
  - Full multi-tab management via CDPTabManager + CDPTab
  - Tab lifecycle events (created, destroyed, navigated)
  - Per-tab event isolation with independent WebSocket connections
  - Context manager: async with CDPBrowser() as browser

CLI (backward-compatible):
  python3 cdp_browser.py navigate <url>
  python3 cdp_browser.py shot [png_path]
  python3 cdp_browser.py dump
  python3 cdp_browser.py eval <js>
  python3 cdp_browser.py tabs
  python3 cdp_browser.py multitab          # Interactive multi-tab demo
"""

import sys
import os
import base64
import json
import urllib.request
import subprocess
import time
import platform
import shutil
import traceback
import tempfile
import asyncio
import itertools
import logging
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List

# ---------------------------------------------------------------------------
# Optional aiohttp import — graceful degradation for environments without it
# ---------------------------------------------------------------------------
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    import websockets as _websockets_mod
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("cdp_browser")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_PORT = 9222
DEFAULT_TIMEOUT = 30  # seconds
RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY = 1  # seconds

from arena.browser.cdp_client.process import (
    find_browser_exe, _resolve_browser_binary, _build_session_env, _build_chromium_cmd,
    _ts, _drain_stderr, _kill_port_processes, _write_diag_file, launch_browser,
)
from arena.browser.cdp_client.tabs_http import list_tabs, get_websocket_url, get_new_tab_url, close_tab
from arena.browser.cdp_client.websocket_adapter import WebsocketsCDPAdapter, _WSMessage
from arena.browser.cdp_client.sync_browser import SyncCDPBrowser
from arena.browser.cdp_client.network_monitor import NetworkRequest, CDPNetworkMonitor
from arena.browser.cdp_client.interceptor import InterceptRule, CDPNetworkInterceptor
from arena.browser.cdp_client.cookies import CDPCookieManager
from arena.browser.cdp_client.browser import CDPBrowser
from arena.browser.cdp_client.tab import CDPTab
from arena.browser.cdp_client.tab_manager import CDPTabManager
from arena.browser.cdp_client.cli import main


# ---------------------------------------------------------------------------
# Browser process management
# ---------------------------------------------------------------------------


















# ---------------------------------------------------------------------------
# HTTP helpers (no aiohttp needed)
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# WebsocketsCDPAdapter — wraps websockets library for CDPBrowser
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Async CDP Browser class
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Multi-tab management: CDPTab and CDPTabManager
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Synchronous fallback (raw socket, no aiohttp needed)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CLI entry point (backward compatible)
# ---------------------------------------------------------------------------




if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Network monitoring and interception
# ---------------------------------------------------------------------------









# ---------------------------------------------------------------------------
# Cookie and session management
# ---------------------------------------------------------------------------

