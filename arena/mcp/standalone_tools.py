"""Standalone MCP tool dispatcher."""
from __future__ import annotations

from pathlib import Path as _Path

from arena.files.sandbox import SENSITIVE_FILE_BASENAMES as _BLOCKED_BASENAMES
from arena.mcp.standalone_common import *  # noqa: F401,F403
from arena.mcp.tool_registry import MCP_TOOLS as TOOLS  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
from arena.util import under_root as _under_root

# The three imports above that are NOT the star import are deliberate: the path
# jail must not depend on names a `import *` might silently stop providing.


class PathJailError(Exception):
    """Raised when a tool argument points outside the user's home."""


def _jail(raw: str) -> str:
    """Resolve a caller-supplied path, refusing anything outside $HOME.

    This dispatcher backs the standalone HTTP/WebSocket MCP servers, which do
    not go through ``arena/mcp/tool_fs.py`` and therefore never inherited its
    jail. Until v4.155.0 fs.read/fs.write/fs.list here accepted absolute paths
    and ``../`` traversal outright -- reading /etc/hostname was a one-liner.
    CodeQL only surfaced it (py/path-injection) once E701 splitting put the
    open() on its own line, which is a fair reminder that a scanner's silence
    is not evidence.

    Mirrors the main dispatcher's rules: sensitive basenames are refused
    outright, and the resolved path must sit under the real home directory
    (resolve() first, so symlinks and ``..`` cannot escape).
    """
    if not raw:
        raise PathJailError("missing 'path' argument")
    expanded = os.path.expanduser(raw)
    if _Path(expanded).name in _BLOCKED_BASENAMES:
        raise PathJailError(f"accessing {_Path(expanded).name} is not allowed")
    resolved = _Path(expanded).resolve()
    home = _Path.home().resolve()
    # Two equivalent checks, deliberately. `under_root` is the shared helper
    # and stays authoritative; the explicit `relative_to` below expresses the
    # same containment locally so a reader -- and a taint analyser that cannot
    # see into arena.util -- can confirm the value is constrained right here.
    # Neither is redundant to the other in intent: if they ever disagree, that
    # is a bug worth crashing on, not a difference to paper over.
    if not _under_root(resolved, home):
        raise PathJailError("path outside home directory")
    try:
        resolved.relative_to(home)
    except ValueError:
        raise PathJailError("path outside home directory") from None
    return str(resolved)

# v4.75.0: bare-name warnings removed. The v4.69.0
# deprecation window has expired; the bare names
# (ping / echo / exec / snapshot) are no longer
# accepted by the dispatcher. Clients that still
# send them will get a clean no-match (the dispatcher
# returns None and the bridge reports no-such-tool).


# v4.78.0: mem.set / mem.get removed. The v4.71.0
# deprecation window has expired; the bare forms are
# no longer accepted by the dispatcher. Clients that
# still send them will get a clean no-match (the
# dispatcher returns None and the bridge reports
# no-such-tool).


def call_tool(name: str, args: dict) -> dict:
    """Диспетчер — возвращает MCP content payload."""
    try:
        # v4.75.0: bare names (ping / echo / exec) removed.
        # Only the namespaced exec.* form is accepted.
        if name == "exec.ping":
            return text_content("pong")
        if name == "exec.echo":
            return text_content(str(args.get("text", "")))
        if name == "exec.exec":
            rc, out, err = run_sd(["bash", "-lc", args["cmd"]], timeout=args.get("timeout", 60))
            return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-5000:]}, ensure_ascii=False))
        if name == "fs.read":
            p = _jail(args["path"])
            with open(p, "rb") as f:
                data = f.read(args.get("max_bytes", 200000))
            return text_content(data.decode("utf-8", "replace"))
        if name == "fs.write":
            p = _jail(args["path"])
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(args["content"])
            return text_content(f"wrote {len(args['content'])} bytes to {p}")
        if name == "fs.list":
            p = _jail(args["path"])
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
            import platform
            import tempfile
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
        # v4.75.0: bare 'snapshot' name removed.
        if name == "exec.snapshot":
            rc, out, err = run_local([os.path.join(BIN, "agentctl"), "skill", "run", "system/sys-snapshot"], timeout=60)
            return text_content(out or err)
        if name == "subagent.spawn":
            cmd_args = [sys.executable, os.path.join(BIN, "subagent.py"), "spawn", args.get("cmd", "")]
            if args.get("name"):
                cmd_args += ["--name", args["name"]]
            if args.get("wait", True):
                cmd_args += ["--wait"]
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
