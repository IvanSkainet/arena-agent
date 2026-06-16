"""Standalone MCP tool dispatcher."""
from __future__ import annotations

from arena.mcp.standalone_common import *  # noqa: F401,F403
from arena.mcp.tool_registry import MCP_TOOLS as TOOLS

def call_tool(name: str, args: dict) -> dict:
    """Диспетчер — возвращает MCP content payload."""
    try:
        if name == "ping": return text_content("pong")
        if name == "echo": return text_content(str(args.get("text", "")))
        if name == "exec":
            rc, out, err = run_sd(["bash", "-lc", args["cmd"]], timeout=args.get("timeout", 60))
            return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-5000:]}, ensure_ascii=False))
        if name == "fs.read":
            p = os.path.expanduser(args["path"])
            with open(p, "rb") as f: data = f.read(args.get("max_bytes", 200000))
            return text_content(data.decode("utf-8", "replace"))
        if name == "fs.write":
            p = os.path.expanduser(args["path"])
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f: f.write(args["content"])
            return text_content(f"wrote {len(args['content'])} bytes to {p}")
        if name == "fs.list":
            p = os.path.expanduser(args["path"])
            return text_content(json.dumps(sorted(os.listdir(p))))
        if name == "browser.search":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "search", args["query"], "--n", str(args.get("n", 5))], timeout=30)
            return text_content(out or err)
        if name == "browser.read":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "read", args["url"]], timeout=30)
            return text_content(out or err)
        if name == "browser.shot":
            import tempfile, platform
            shots = os.path.join(HOME, "arena-bridge", "reports", "shots")
            os.makedirs(shots, exist_ok=True)
            png = os.path.join(shots, f"mcp-{int(time.time())}.png")
            ud = os.path.join(tempfile.gettempdir(), f"cr-mcp-{os.getpid()}")
            chrome_candidates = [
                    "chromium", "chrome", "google-chrome", "google-chrome-stable",
                    "librewolf", "brave", "brave-browser", "firefox", "vivaldi", "yandex-browser", "opera", "tor-browser", "arc", "comet",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Google", "Chrome", "Application", "chrome.exe"),
                    r"C:\Program Files\LibreWolf\librewolf.exe",
                    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                    r"C:\Program Files\Mozilla Firefox\firefox.exe",
                    r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
                    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Yandex", "YandexBrowser", "Application", "browser.exe"),
                    r"C:\Program Files\Yandex\YandexBrowser\Application\browser.exe",
                    r"C:\Program Files\Opera\launcher.exe",
                    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Opera", "launcher.exe"),
                    r"C:\Program Files\Tor Browser\Browser\firefox.exe",
                    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Arc", "Arc.exe"),
                    r"C:\Program Files\Comet\comet.exe",
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    "msedge.exe"
                ]
            if platform.system() == "Windows":
                chrome_candidates = [
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    "msedge.exe",
                    "chrome.exe",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files\Chromium\Application\chrome.exe",
                    r"C:\Program Files\LibreWolf\librewolf.exe",
                ]
            chrome_exe = next((shutil.which(c) or (c if os.path.exists(c) else None) for c in chrome_candidates if shutil.which(c) or os.path.exists(c)), None) or "chrome.exe"
            rc, out, err = run_sd([chrome_exe, "--headless=new", "--no-sandbox", "--disable-gpu",
                                    f"--user-data-dir={ud}", "--window-size=1366,768",
                                    f"--screenshot={png}", args["url"]], timeout=45)
            return text_content(json.dumps({"ok": rc == 0, "screenshot": png, "url": args["url"]}))
        if name == "mem.set":
            tags = args.get("tags") or []
            cmd_args = [os.path.join(BIN, "agentctl"), "mem", "set", args["key"], args["value"]]
            if tags: cmd_args += ["--tags"] + list(tags)
            rc, out, err = run_local(cmd_args, timeout=15)
            return text_content(out or err)
        if name == "mem.get":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "mem", "get", args["query"]], timeout=15)
            return text_content(out or err)
        if name == "sys.status":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "sys", "status"], timeout=30)
            return text_content(out or err)
        if name == "skill.list":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "list"], timeout=15)
            return text_content(out or err)
        if name == "skill.run":
            sk = args.get("name", "")
            extra = args.get("args") or []
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "run", sk] + list(extra), timeout=300)
            return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-3000:]}, ensure_ascii=False))
        if name == "hooks.list":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "hooks_runner.py"), "list"], timeout=10)
            return text_content(out or err)
        if name == "snapshot":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "run", "system/sys-snapshot"], timeout=60)
            return text_content(out or err)
        if name == "subagent.spawn":
            cmd_args = [sys.executable, os.path.join(BIN, "subagent.py"), "spawn", args.get("cmd", "")]
            if args.get("name"): cmd_args += ["--name", args["name"]]
            if args.get("wait", True): cmd_args += ["--wait"]
            cmd_args += ["--timeout", str(args.get("timeout", 300))]
            rc, out, err = run_local(cmd_args, timeout=args.get("timeout", 300) + 30)
            return text_content(out or err)
        if name == "subagent.list":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "subagent.py"), "list"], timeout=10)
            return text_content(out or err)
        if name == "memory.recall":
            cmd_args = [sys.executable, os.path.join(BIN, "memory_recall.py"), "recall", args.get("query", ""),
                        "--top", str(args.get("top", 5))]
            rc, out, err = run_local(cmd_args, timeout=15)
            return text_content(out or err)
        if name == "memory.digest":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "memory_recall.py"), "digest"], timeout=15)
            return text_content(out or err)
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {type(e).__name__}: {e}"}]}
    return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
