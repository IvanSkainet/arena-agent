"""MCP browser helper tools."""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
import time
from typing import Any

from arena.browser.navigation_policy import NavigationRejected, check_navigation
from arena.mcp.tool_utils import text_content


def handle_browser_tool(name: str, args: dict[str, Any], *, ctx, run_local, run_sd) -> dict[str, Any] | None:
    if name == "browser.search":
        rc, out, err = run_local([sys.executable, os.path.join(ctx.bin_dir, "py_browser.py"),
                                  "search", args.get("query", ""), "--n", str(args.get("n", 5))], timeout=30)
        return text_content(out or err)
    if name == "browser.read":
        rc, out, err = run_local([sys.executable, os.path.join(ctx.bin_dir, "py_browser.py"),
                                  "read", args.get("url", "")], timeout=30)
        return text_content(out or err)
    if name != "browser.shot":
        return None

    # A headless Chromium launched with a URL on its command line navigates to
    # it exactly like Page.navigate does, so this path needs the same policy;
    # it simply does not go through CDP to get there.
    try:
        url = check_navigation(args.get("url"))
    except NavigationRejected as exc:
        return text_content(json.dumps({"ok": False, "error": str(exc)}))

    shots = str(ctx.reports_dir / "shots")
    os.makedirs(shots, exist_ok=True)
    png = os.path.join(shots, f"mcp-{int(time.time())}.png")
    ud = os.path.join(tempfile.gettempdir(), f"cr-mcp-{os.getpid()}")
    chrome_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "msedge.exe", "chrome.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\LibreWolf\librewolf.exe",
    ] if platform.system() == "Windows" else [
        "chromium", "chrome", "google-chrome", "google-chrome-stable",
        "librewolf", "brave", "firefox", "vivaldi",
    ]
    chrome_exe = next(
        ((shutil.which(c) or (c if os.path.exists(c) else None))
         for c in chrome_candidates if shutil.which(c) or os.path.exists(c)),
        None,
    ) or "chrome.exe"
    rc, out, err = run_sd([chrome_exe, "--headless=new", "--no-sandbox", "--disable-gpu",
                           f"--user-data-dir={ud}", "--window-size=1366,768",
                           f"--screenshot={png}", url], timeout=45)
    return text_content(json.dumps({"ok": rc == 0, "screenshot": png, "url": url}))
