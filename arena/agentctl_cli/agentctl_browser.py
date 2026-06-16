"""agentctl browser commands."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

from arena.agentctl_cli.agentctl_common import ROOT, bridge_get


def search(args):
    q = " ".join(args) if args else "test"
    try:
        for res in bridge_get(f"/v1/browser/search?q={quote(q)}").get("results", []):
            print(f"  {res.get('title','?')}")
            print(f"    {res.get('url','')}")
            print(f"    {res.get('snippet','')[:100]}\n")
    except Exception as e:
        print(f"Error: {e}")


def read(args):
    url = args[0] if args else "https://example.com"
    try:
        r = bridge_get(f"/v1/browser/read?url={quote(url, safe=':/?&=%')}")
        print(r.get("text", r.get("content", json.dumps(r, indent=2, ensure_ascii=False)[:500])))
    except Exception as e:
        print(f"Error: {e}")


def dump(args):
    url = args[0] if args else "https://example.com"
    try:
        r = bridge_get(f"/v1/browser/dump?url={quote(url, safe=':/?&=%')}")
        print(r.get("text", json.dumps(r, indent=2, ensure_ascii=False)[:500]))
    except Exception as e:
        print(f"Error: {e}")


def head(args):
    url = args[0] if args else "https://example.com"
    try:
        print(json.dumps(bridge_get(f"/v1/browser/head?url={quote(url, safe=':/?&=%')}"), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")


def shot(args):
    url = args[0] if args else "https://example.com"
    shots_dir = ROOT / "reports" / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    png = str(shots_dir / f"shot-{int(time.time())}.png")
    candidates = (
        [os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
         r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
         r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
        if platform.system() == "Windows"
        else ["chromium", "chrome", "google-chrome", "google-chrome-stable", "librewolf", "brave", "brave-browser", "firefox"]
    )
    exe = next((c for c in candidates if os.path.isfile(c) or shutil.which(c)), None)
    if not exe:
        print("No browser found for screenshot")
        sys.exit(1)
    ud = os.path.join(tempfile.gettempdir(), f"cr-{os.getpid()}")
    cmd = [exe, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={ud}",
           "--window-size=1366,768", f"--screenshot={png}", url]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        print(f"Screenshot saved: {png} ({os.path.getsize(png)//1024}KB)" if os.path.exists(png) else "Screenshot failed")
    except Exception as e:
        print(f"Error: {e}")
