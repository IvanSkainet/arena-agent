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

from arena.browser.navigation_policy import navigation_error
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

    # `browser.read` is validated inside py_browser.py; this one hands the URL
    # to Chromium on the command line, so it has to ask the same question
    # itself. Blank is not meaningful for a screenshot, so it is not allowed.
    shot_url = args.get("url", "")
    nav_error = navigation_error(shot_url, allow_blank=False)
    if nav_error:
        return text_content(json.dumps({"ok": False, "error": nav_error}))

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
                           f"--screenshot={png}", shot_url], timeout=45)
    return text_content(json.dumps({"ok": rc == 0, "screenshot": png, "url": shot_url}))
