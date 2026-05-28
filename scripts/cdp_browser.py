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
import tempfile
import asyncio
import itertools
import logging
from typing import Optional, Callable, Any, Dict, List

# ---------------------------------------------------------------------------
# Optional aiohttp import — graceful degradation for environments without it
# ---------------------------------------------------------------------------
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

logger = logging.getLogger("cdp_browser")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_PORT = 9222
DEFAULT_TIMEOUT = 30  # seconds
RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY = 1  # seconds


# ---------------------------------------------------------------------------
# Browser process management
# ---------------------------------------------------------------------------
def find_browser_exe() -> str:
    """Find a Chromium-based browser executable on the system."""
    chrome_candidates = [
        "chromium", "chrome", "google-chrome", "google-chrome-stable",
        "librewolf", "brave", "brave-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.path.expanduser("~"), "AppData", "Local",
                     "Google", "Chrome", "Application", "chrome.exe"),
        r"C:\Program Files\LibreWolf\librewolf.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "msedge.exe",
    ]
    for c in chrome_candidates:
        p = shutil.which(c)
        if p:
            return p
        if os.path.exists(c):
            return c
    return "chrome.exe" if platform.system() == "Windows" else "chromium"


def _resolve_browser_binary() -> str:
    """Find the actual browser binary, bypassing wrapper scripts.

    On some distros (e.g. CachyOS), /usr/bin/chromium is a shell wrapper
    that adds --ozone-platform-hint=auto and other flags which conflict
    with headless mode. We need the real binary at /usr/lib/chromium/chromium.
    """
    exe = find_browser_exe()
    if platform.system() != "Linux":
        return exe

    # Check if the found exe is a wrapper script by reading its first line
    real_path = shutil.which(exe) or exe
    try:
        with open(real_path, "rb") as f:
            first_bytes = f.read(64)
        # If it starts with #! it's a script/wrapper, not a real binary
        if first_bytes.startswith(b"#!/") or first_bytes.startswith(b"#! "):
            # Try common real binary locations
            for candidate in [
                "/usr/lib/chromium/chromium",
                "/usr/lib/chromium-browser/chromium-browser",
                "/usr/lib64/chromium/chromium",
                "/opt/chromium/chrome",
                "/opt/google/chrome/chrome",
                "/opt/google/chrome/google-chrome",
                "/usr/bin/chromium-browser",
            ]:
                if os.path.isfile(candidate):
                    # Verify it's a real ELF binary
                    try:
                        with open(candidate, "rb") as f:
                            magic = f.read(4)
                        if magic == b"\x7fELF":
                            logger.info("[CDP] Bypassing wrapper %s, using real binary %s", real_path, candidate)
                            return candidate
                    except Exception:
                        pass
    except Exception:
        pass
    return real_path


def _build_session_env() -> dict:
    """Build an environment dict with session/GUI variables for subprocess.

    When running inside a systemd user service, the environment is minimal:
    no DBUS_SESSION_BUS_ADDRESS, no XDG_RUNTIME_DIR, no DISPLAY, etc.
    This function constructs these from known system paths so that Chromium
    can function in headless mode.
    """
    env = os.environ.copy()
    uid = os.getuid()

    # XDG_RUNTIME_DIR — needed by many Linux components
    if not env.get("XDG_RUNTIME_DIR"):
        xdg = f"/run/user/{uid}"
        if os.path.isdir(xdg):
            env["XDG_RUNTIME_DIR"] = xdg

    # DBUS_SESSION_BUS_ADDRESS — needed for D-Bus communication
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        dbus_path = f"/run/user/{uid}/bus"
        if os.path.exists(dbus_path):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_path}"

    # DISPLAY — needed for fontconfig and some Chromium subsystems
    if not env.get("DISPLAY") and os.path.exists("/tmp/.X11-unix"):
        try:
            for xfile in os.listdir("/tmp/.X11-unix"):
                if xfile.startswith("X"):
                    env["DISPLAY"] = f":{xfile[1:]}"
                    break
        except Exception:
            pass

    # WAYLAND_DISPLAY — for Wayland-based sessions
    if not env.get("WAYLAND_DISPLAY") and env.get("XDG_RUNTIME_DIR"):
        wayland_sock = os.path.join(env["XDG_RUNTIME_DIR"], "wayland-0")
        if os.path.exists(wayland_sock):
            env["WAYLAND_DISPLAY"] = "wayland-0"

    return env


def _build_chromium_cmd(exe: str, port: int, headless: bool, user_data_dir: str) -> list:
    """Build the Chromium command line with all necessary flags.

    Critical flags for headless operation in a systemd service:
    - --ozone-platform=headless: REQUIRED for headless mode. Without this,
      Chromium tries to connect to Wayland/X11 display server and fails
      silently when no display is available (systemd service environment).
    - --disable-setuid-sandbox: Needed when running in constrained cgroups.
    - --no-sandbox: Disables the Chrome sandbox (needed for rootless containers).
    - --disable-dev-shm-usage: Use /tmp instead of /dev/shm for shared memory.
    """
    cmd = [
        exe,
        f"--remote-debugging-port={port}",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--metrics-recording-only",
        f"--user-data-dir={user_data_dir}",
    ]
    if headless:
        cmd.append("--headless=new")
        # CRITICAL: --ozone-platform=headless is required for Chromium headless
        # mode to work without a display server. Without this flag, Chromium
        # attempts to auto-detect the display platform (Wayland/X11), fails
        # silently, and exits with no error output. This was the root cause
        # of the CDP connect timeout bug in v1.9.5 through v1.9.9.
        cmd.append("--ozone-platform=headless")
    return cmd


def _drain_stderr(proc, log_path):
    """Drain subprocess stderr to a log file in a background thread."""
    try:
        with open(log_path, "ab") as log_file:
            for line in proc.stderr:
                log_file.write(line if isinstance(line, bytes) else line.encode(errors="replace"))
    except Exception:
        pass


def _kill_existing_browser(port: int = DEFAULT_PORT) -> None:
    """Kill any existing Chromium process using the debug port.

    This prevents 'address already in use' errors when reconnecting.
    Only kills processes that are actually listening on the port.
    """
    import signal as _signal
    try:
        # Find PIDs listening on the CDP port
        result = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            # ss output format: ... users:(("chromium",pid=1234,fd=...))
            if "pid=" in line:
                import re
                pids = re.findall(r'pid=(\d+)', line)
                for pid_str in pids:
                    try:
                        pid = int(pid_str)
                        if pid != os.getpid():  # Don't kill ourselves
                            os.kill(pid, _signal.SIGTERM)
                            logger.info("[CDP] Killed stale Chromium pid %d on port %d", pid, port)
                    except (ProcessLookupError, PermissionError, ValueError):
                        pass
    except Exception:
        pass


def launch_browser(port: int = DEFAULT_PORT, headless: bool = True) -> subprocess.Popen:
    """Launch a browser with remote debugging enabled. Returns the Popen object.

    This function is NON-BLOCKING: it starts Chromium and returns immediately.
    Port readiness is checked by the caller (CDPBrowser.connect / CDPTabManager.connect)
    via list_tabs() retries in async code with proper timeouts.

    Launch strategy (in order):
    1. Direct launch with session_env (fastest, works if cgroup allows it)
    2. If direct launch crashes (exits within 2s), try systemd-run --scope

    Key design decisions:
    - Returns QUICKLY — no blocking sleeps for port readiness.
      The caller handles port readiness checks asynchronously.
    - Captures stderr to a log file for diagnostics.
    - Attaches launch diagnostics to the Popen object as _cdp_launch_diag.
    """
    import threading

    # Kill any stale Chromium processes on the same port
    _kill_existing_browser(port)

    exe = _resolve_browser_binary()
    logger.info("[CDP] Launching browser: %s (headless=%s, port=%d)", exe, headless, port)

    ud = os.path.join(tempfile.gettempdir(), f"cdp-browser-{os.getpid()}")
    os.makedirs(ud, exist_ok=True)
    stderr_log_path = os.path.join(ud, "chromium-launch.log")

    cmd = _build_chromium_cmd(exe, port, headless, ud)
    session_env = _build_session_env()

    launch_diag = {
        "exe": exe,
        "headless": headless,
        "port": port,
        "user_data_dir": ud,
        "cmd_summary": " ".join(cmd[:6]) + " ...",
        "env_has_dbus": bool(session_env.get("DBUS_SESSION_BUS_ADDRESS")),
        "env_has_xdg": bool(session_env.get("XDG_RUNTIME_DIR")),
        "env_has_display": bool(session_env.get("DISPLAY")),
        "stderr_log": stderr_log_path,
    }

    # --- Strategy 1: Direct launch (always try first) ---
    logger.info("[CDP] Attempting direct browser launch: %s", " ".join(cmd[:4]))
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=session_env,
        )
        # Drain stderr in background thread to prevent pipe deadlock
        threading.Thread(target=_drain_stderr, args=(proc, stderr_log_path), daemon=True).start()

        # Quick check: did the process exit immediately? (2 second grace period)
        time.sleep(2)
        if proc.poll() is None:
            # Process is still running — direct launch looks good!
            logger.info("[CDP] Direct launch succeeded (pid %d)", proc.pid)
            launch_diag["method"] = "direct"
            proc._cdp_launch_diag = launch_diag
            return proc
        else:
            # Direct launch failed — process exited within 2 seconds
            diag = ""
            try:
                with open(stderr_log_path, "r") as f:
                    diag = f.read().strip()[:2000]
            except Exception:
                pass
            logger.warning("[CDP] Direct launch failed (code %d). stderr: %s",
                           proc.returncode, diag[:500] or "(empty)")
            launch_diag["direct_rc"] = proc.returncode
            launch_diag["direct_error"] = diag[:800]
    except Exception as e:
        logger.warning("[CDP] Direct launch exception: %s", e)
        launch_diag["direct_exception"] = str(e)

    # --- Strategy 2: systemd-run --user --scope ---
    # Only try if we're in a systemd service and systemd-run is available
    in_systemd = os.environ.get("INVOCATION_ID") or os.environ.get("JOURNAL_STREAM")
    if in_systemd and platform.system() == "Linux" and shutil.which("systemd-run"):
        logger.info("[CDP] Attempting systemd-run --user --scope launch")
        # Clear the log file for the new attempt
        try:
            with open(stderr_log_path, "w") as f:
                pass
        except Exception:
            pass

        # Build -E env flags for Chromium inside the scope
        env_flags = []
        for var in ["DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
                     "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
                     "XDG_CURRENT_DESKTOP"]:
            val = session_env.get(var)
            if val:
                env_flags += ["-E", f"{var}={val}"]

        scope_cmd = ["systemd-run", "--user", "--scope"] + env_flags + ["--"] + cmd
        logger.info("[CDP] scope_cmd: %s", " ".join(scope_cmd[:6]) + " ...")

        try:
            proc = subprocess.Popen(
                scope_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=session_env,
            )
            # Drain stderr in background thread
            threading.Thread(target=_drain_stderr, args=(proc, stderr_log_path), daemon=True).start()

            # Quick check: did systemd-run exit immediately (failure)?
            time.sleep(3)
            if proc.poll() is None:
                logger.info("[CDP] systemd-run launch succeeded (pid %d)", proc.pid)
                launch_diag["method"] = "systemd-run-scope"
                proc._cdp_launch_diag = launch_diag
                return proc
            else:
                # systemd-run exited quickly — probably couldn't create scope
                diag = ""
                try:
                    with open(stderr_log_path, "r") as f:
                        diag = f.read().strip()[:2000]
                except Exception:
                    pass
                logger.error("[CDP] systemd-run failed (code %d). stderr: %s",
                             proc.returncode, diag[:500] or "(empty)")
                launch_diag["systemd_run_rc"] = proc.returncode
                launch_diag["systemd_run_error"] = diag[:800]
        except Exception as e:
            logger.error("[CDP] systemd-run exception: %s", e)
            launch_diag["systemd_run_exception"] = str(e)
    else:
        launch_diag["systemd_run_skipped"] = True
        if not in_systemd:
            launch_diag["skip_reason"] = "not in systemd service"
        elif platform.system() != "Linux":
            launch_diag["skip_reason"] = "not Linux"
        else:
            launch_diag["skip_reason"] = "systemd-run not found"

    # All strategies failed — return a dummy Popen with diagnostics
    logger.error("[CDP] All browser launch strategies failed. Diag: %s", launch_diag)
    launch_diag["all_failed"] = True

    # Create a fake Popen that's already dead, with diagnostics attached
    try:
        proc = subprocess.Popen(["true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.wait(timeout=1)
    except Exception:
        proc = None

    if proc is not None:
        proc._cdp_launch_diag = launch_diag
    return proc


# ---------------------------------------------------------------------------
# HTTP helpers (no aiohttp needed)
# ---------------------------------------------------------------------------
def list_tabs(port: int = DEFAULT_PORT) -> List[Dict[str, Any]]:
    """List all browser tabs via the HTTP debug endpoint."""
    url = f"http://127.0.0.1:{port}/json/list"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return []


def get_websocket_url(port: int = DEFAULT_PORT, tab_index: int = 0) -> Optional[str]:
    """Get the WebSocket debugger URL for a specific tab."""
    tabs = list_tabs(port)
    page_tabs = [t for t in tabs if t.get("type") == "page" and "webSocketDebuggerUrl" in t]
    if page_tabs and 0 <= tab_index < len(page_tabs):
        return page_tabs[tab_index]["webSocketDebuggerUrl"]
    return None


def get_new_tab_url(port: int = DEFAULT_PORT) -> Optional[str]:
    """Open a new tab and return its WebSocket URL.

    Uses PUT method on /json/new (required by Chromium-based browsers).
    Some browsers also accept GET, but PUT is the standard.
    """
    url = f"http://127.0.0.1:{port}/json/new"
    try:
        req = urllib.request.Request(url, method="PUT")
        with urllib.request.urlopen(req, timeout=5) as r:
            tab = json.loads(r.read().decode())
            return tab.get("webSocketDebuggerUrl")
    except Exception:
        # Fallback: try GET (some older Chromium versions)
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                tab = json.loads(r.read().decode())
                return tab.get("webSocketDebuggerUrl")
        except Exception:
            return None


def close_tab(tab_id: str, port: int = DEFAULT_PORT) -> bool:
    """Close a tab by its id."""
    url = f"http://127.0.0.1:{port}/json/close/{tab_id}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.read().decode().strip() == "Target is closing"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Async CDP Browser class
# ---------------------------------------------------------------------------
class CDPBrowser:
    """Async Chrome DevTools Protocol browser controller.

    Usage:
        async with CDPBrowser() as browser:
            await browser.navigate("https://example.com")
            await browser.screenshot("out.png")
            html = await browser.dump_dom()
            result = await browser.eval_js("1 + 2")
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        headless: bool = True,
        auto_launch: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        tab_index: int = 0,
    ):
        self.port = port
        self.headless = headless
        self.auto_launch = auto_launch
        self.timeout = timeout
        self.tab_index = tab_index

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._req_id = itertools.count(1)
        self._pending: Dict[int, asyncio.Future] = {}
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._browser_proc: Optional[subprocess.Popen] = None
        self._closing = False
        self._reconnecting = False

    # -- Context manager ---------------------------------------------------

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # -- Connection management ---------------------------------------------

    async def connect(self) -> None:
        """Connect to the browser's CDP WebSocket endpoint."""
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for async CDP. Install with: pip install aiohttp")

        ws_url = get_websocket_url(self.port, self.tab_index)

        if ws_url is None and self.auto_launch:
            loop = asyncio.get_running_loop()
            self._browser_proc = await loop.run_in_executor(
                None, launch_browser, self.port, self.headless)
            # Check if browser process died immediately
            if self._browser_proc and self._browser_proc.poll() is not None:
                launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                raise ConnectionError(
                    f"Browser process exited immediately (rc={self._browser_proc.returncode}). "
                    f"Launch diag: {launch_diag}"
                )
            # Retry until the debug port is ready (up to 15 seconds)
            for _ in range(15):
                ws_url = get_websocket_url(self.port, self.tab_index)
                if ws_url:
                    break
                # Check if browser crashed
                if self._browser_proc and self._browser_proc.poll() is not None:
                    launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                    raise ConnectionError(
                        f"Browser crashed during startup (rc={self._browser_proc.returncode}). "
                        f"Launch diag: {launch_diag}"
                    )
                await asyncio.sleep(1)

        if ws_url is None:
            raise ConnectionError(f"Cannot connect to browser CDP on port {self.port}")

        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(ws_url, heartbeat=30)
        except Exception:
            await self._session.close()
            raise

        # Enable core domains
        await self.send("Page.enable")
        await self.send("Runtime.enable")

        # Start the WebSocket listener
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info("[CDP] Connected to %s", ws_url)

    async def close(self) -> None:
        """Close the WebSocket connection and clean up."""
        self._closing = True

        # Cancel pending futures so callers don't hang
        for msg_id, future in list(self._pending.items()):
            if not future.done():
                future.cancel()
        self._pending.clear()

        # Only cancel listener if we're not inside it (avoid deadlock)
        if self._listener_task and not self._reconnecting:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()

        if self._session and not self._session.closed:
            await self._session.close()

        if self._browser_proc:
            self._browser_proc.terminate()
            try:
                self._browser_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._browser_proc.kill()

        self._listener_task = None
        logger.info("[CDP] Connection closed")

    async def reconnect(self) -> None:
        """Attempt to reconnect after a connection drop.

        Called from within _listen_loop, so we must avoid the deadlock
        where close() tries to await the listener task (itself).
        """
        self._reconnecting = True
        self._closing = True

        # Cancel pending futures
        for msg_id, future in list(self._pending.items()):
            if not future.done():
                future.cancel()
        self._pending.clear()

        # Close WS and session without cancelling the listener task
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

        self._closing = False
        self._reconnecting = False

        for attempt in range(1, RECONNECT_ATTEMPTS + 1):
            logger.info("[CDP] Reconnect attempt %d/%d", attempt, RECONNECT_ATTEMPTS)
            try:
                await self.connect()
                return
            except Exception as e:
                logger.warning("[CDP] Reconnect failed: %s", e)
                await asyncio.sleep(RECONNECT_DELAY)
        raise ConnectionError("Failed to reconnect after all attempts")

    # -- Low-level CDP communication ---------------------------------------

    async def send(self, method: str, params: Optional[Dict] = None,
                   timeout: Optional[float] = None) -> Dict:
        """Send a CDP command and wait for its response.

        Args:
            method: CDP method name (e.g., "Page.navigate")
            params: Optional parameters dict
            timeout: Override default timeout for this call

        Returns:
            The CDP response dict (with "id" and "result" or "error")

        Raises:
            asyncio.TimeoutError: if the response doesn't arrive in time
            ConnectionError: if the WebSocket is closed
        """
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket is not connected")

        msg_id = next(self._req_id)
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[msg_id] = future

        await self._ws.send_json(msg)
        logger.debug("[CDP] -> %s %s (id=%d)", method, params or "", msg_id)

        effective_timeout = timeout or self.timeout
        try:
            result = await asyncio.wait_for(future, effective_timeout)
            if "error" in result:
                logger.warning("[CDP] Error response for %s: %s", method, result["error"])
            return result
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise
        except Exception:
            self._pending.pop(msg_id, None)
            raise

    # -- Event system ------------------------------------------------------

    def on(self, event_name: str, callback: Callable[[Dict], Any]) -> None:
        """Register a callback for a CDP event.

        Args:
            event_name: CDP event name (e.g., "Page.loadEventFired")
            callback: Function to call with the event params dict
        """
        self._event_handlers.setdefault(event_name, []).append(callback)

    def off(self, event_name: str, callback: Callable) -> None:
        """Unregister a callback for a CDP event."""
        handlers = self._event_handlers.get(event_name, [])
        if callback in handlers:
            handlers.remove(callback)

    async def wait_for_event(self, event_name: str, timeout: Optional[float] = None) -> Dict:
        """Wait for a specific CDP event and return its params.

        This is a convenience method that creates a one-shot listener.
        """
        effective_timeout = timeout or self.timeout
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def one_shot(params: Dict):
            if not future.done():
                future.set_result(params)

        self.on(event_name, one_shot)
        try:
            return await asyncio.wait_for(future, effective_timeout)
        finally:
            self.off(event_name, one_shot)

    # -- WebSocket listener ------------------------------------------------

    async def _listen_loop(self) -> None:
        """Background task that reads WebSocket messages and dispatches them."""
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    # Dispatch response to pending future
                    msg_id = data.get("id")
                    if msg_id and msg_id in self._pending:
                        future = self._pending.pop(msg_id)
                        if not future.done():
                            future.set_result(data)
                        continue

                    # Dispatch event to handlers
                    method = data.get("method")
                    if method:
                        params = data.get("params", {})
                        # Call registered handlers
                        for handler in self._event_handlers.get(method, []):
                            try:
                                result = handler(params)
                                if asyncio.iscoroutine(result):
                                    asyncio.create_task(result)
                            except Exception as e:
                                logger.error("[CDP] Event handler error for %s: %s", method, e)

                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                    logger.warning("[CDP] WebSocket closed/error")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[CDP] Listener error: %s", e)

        # If we got here unexpectedly, try reconnect
        if not self._closing:
            logger.info("[CDP] Connection lost, attempting reconnect...")
            try:
                await self.reconnect()
            except ConnectionError:
                logger.error("[CDP] Reconnect failed")

    # -- High-level convenience methods ------------------------------------

    async def navigate(self, url: str, wait: bool = True,
                       timeout: Optional[float] = None) -> Dict:
        """Navigate to a URL. Optionally wait for the page to fully load.

        Args:
            url: The URL to navigate to
            wait: If True, wait for Page.loadEventFired
            timeout: Override default timeout

        Returns:
            The Page.navigate response
        """
        effective_timeout = timeout or self.timeout

        if wait:
            # Set up load listener before navigating
            load_future = asyncio.ensure_future(
                self.wait_for_event("Page.loadEventFired", effective_timeout + 10)
            )
            try:
                result = await self.send("Page.navigate", {"url": url}, effective_timeout)
                await load_future  # Wait for page to actually load
                return result
            except asyncio.TimeoutError:
                load_future.cancel()
                raise
        else:
            return await self.send("Page.navigate", {"url": url}, effective_timeout)

    async def screenshot(self, path: Optional[str] = None,
                         timeout: Optional[float] = None) -> Optional[bytes]:
        """Capture a screenshot of the current page.

        Args:
            path: If provided, save PNG to this path
            timeout: Override default timeout

        Returns:
            Raw PNG bytes, or None on failure
        """
        res = await self.send("Page.captureScreenshot", timeout=timeout)
        if res and "result" in res and "data" in res["result"]:
            img_bytes = base64.b64decode(res["result"]["data"])
            if path:
                with open(path, "wb") as f:
                    f.write(img_bytes)
                logger.info("[CDP] Screenshot saved to %s (%d bytes)", path, len(img_bytes))
            return img_bytes
        return None

    async def dump_dom(self, timeout: Optional[float] = None) -> Optional[str]:
        """Dump the outerHTML of the current page.

        Returns:
            The HTML string, or None on failure
        """
        res = await self.send(
            "Runtime.evaluate",
            {"expression": "document.documentElement.outerHTML"},
            timeout=timeout,
        )
        if res and "result" in res and "result" in res["result"]:
            return res["result"]["result"].get("value")
        return None

    async def eval_js(self, expression: str,
                      timeout: Optional[float] = None) -> Any:
        """Evaluate a JavaScript expression in the page context.

        Returns:
            The result value from the Runtime.evaluate response
        """
        res = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            timeout=timeout,
        )
        if res and "result" in res and "result" in res["result"]:
            return res["result"]["result"].get("value")
        return None

    async def get_tabs(self) -> List[Dict[str, Any]]:
        """List all open browser tabs."""
        return list_tabs(self.port)

    async def new_tab(self, url: str = "about:blank") -> Optional[str]:
        """Open a new browser tab and optionally navigate to a URL.

        Note: Navigation of the new tab requires a separate CDP connection
        to that tab's WebSocket URL. This method only creates the tab.
        Use navigate() on a CDPBrowser connected to the new tab to navigate it.

        Returns:
            The WebSocket URL of the new tab, or None on failure
        """
        ws_url = get_new_tab_url(self.port)
        return ws_url

    async def close_tab_by_id(self, tab_id: str) -> bool:
        """Close a tab by its target ID."""
        return close_tab(tab_id, self.port)

    async def get_cookies(self, timeout: Optional[float] = None) -> List[Dict]:
        """Get all cookies for the current page."""
        res = await self.send("Network.getCookies", timeout=timeout)
        if res and "result" in res:
            return res["result"].get("cookies", [])
        return []

    async def set_cookie(self, name: str, value: str, domain: str = "",
                         path: str = "/", timeout: Optional[float] = None) -> bool:
        """Set a cookie."""
        params = {"name": name, "value": value, "path": path}
        if domain:
            params["domain"] = domain
        res = await self.send("Network.setCookie", params, timeout=timeout)
        return res and res.get("result", {}).get("success", False)

    async def delete_cookie(self, name: str, domain: str = "",
                            timeout: Optional[float] = None) -> None:
        """Delete a cookie by name."""
        params = {"name": name}
        if domain:
            params["domain"] = domain
        await self.send("Network.deleteCookie", params, timeout=timeout)

    async def get_current_url(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get the current page URL."""
        return await self.eval_js("window.location.href", timeout=timeout)

    async def get_title(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get the current page title."""
        return await self.eval_js("document.title", timeout=timeout)

    async def click(self, selector: str, timeout: Optional[float] = None) -> bool:
        """Click an element matching a CSS selector.

        Uses JSON encoding to prevent JS injection via the selector string.
        Returns True if the element was found and clicked, False otherwise.
        """
        safe_selector = json.dumps(selector)  # JSON-encode to prevent injection
        expr = f'(function(){{var el=document.querySelector({safe_selector});if(el){{el.click();return true}}return false}})()'
        result = await self.eval_js(expr, timeout=timeout)
        return result is True

    async def type_text(self, selector: str, text: str,
                        timeout: Optional[float] = None) -> bool:
        """Type text into an element matching a CSS selector.

        Uses JSON encoding to prevent JS injection via selector and text strings.
        Returns True if the element was found and text was set, False otherwise.
        """
        safe_selector = json.dumps(selector)
        safe_text = json.dumps(text)
        expr = f'(function(){{var el=document.querySelector({safe_selector});if(el){{el.focus();el.value={safe_text};el.dispatchEvent(new Event("input",{{bubbles:true}}));return true}}return false}})()'
        result = await self.eval_js(expr, timeout=timeout)
        return result is True

    async def wait_for_selector(self, selector: str, poll_interval: float = 0.5,
                                timeout: Optional[float] = None) -> bool:
        """Wait until a CSS selector matches an element in the DOM.

        Uses JSON encoding to prevent JS injection via the selector string.
        Returns True if found within timeout, False otherwise.
        """
        effective_timeout = timeout or self.timeout
        loop = asyncio.get_running_loop()
        deadline = loop.time() + effective_timeout
        safe_selector = json.dumps(selector)
        expr = f'document.querySelector({safe_selector}) !== null'

        while loop.time() < deadline:
            result = await self.eval_js(expr, timeout=5)
            if result:
                return True
            await asyncio.sleep(poll_interval)
        return False


# ---------------------------------------------------------------------------
# Multi-tab management: CDPTab and CDPTabManager
# ---------------------------------------------------------------------------

class CDPTab:
    """Represents a single browser tab with its own CDP connection.

    Each CDPTab wraps a CDPBrowser instance connected to a specific tab's
    WebSocket URL, providing isolated operations and event handling.

    Usage:
        tab = CDPTab(target_id="ABC123", ws_url="ws://127.0.0.1:9222/devtools/page/ABC123")
        await tab.connect()
        await tab.navigate("https://example.com")
        title = await tab.get_title()
        await tab.close()
    """

    def __init__(
        self,
        target_id: str,
        ws_url: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        title: str = "",
        url: str = "",
    ):
        self.target_id = target_id
        self.ws_url = ws_url
        self.port = port
        self.timeout = timeout
        self.title = title
        self.url = url

        self._browser: Optional[CDPBrowser] = None
        self._connected = False

    # -- Properties ----------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether this tab has an active CDP connection."""
        return self._connected and self._browser is not None

    # -- Context manager -----------------------------------------------------

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    # -- Connection management -----------------------------------------------

    async def connect(self) -> None:
        """Establish a CDP WebSocket connection to this tab."""
        if self._connected and self._browser is not None:
            return

        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for CDPTab. Install with: pip install aiohttp")

        # Create a CDPBrowser instance configured for this specific tab
        self._browser = CDPBrowser(
            port=self.port,
            auto_launch=False,  # Don't auto-launch — tab already exists
            timeout=self.timeout,
        )

        # Connect directly using the tab's WebSocket URL
        self._browser._session = aiohttp.ClientSession()
        try:
            self._browser._ws = await self._browser._session.ws_connect(
                self.ws_url, heartbeat=30
            )
        except Exception:
            await self._browser._session.close()
            self._browser = None
            raise

        # Disable auto-reconnect: if WS drops, _listen_loop would call
        # reconnect() which connects to tab_index=0, NOT this tab.
        # Instead, let CDPTabManager handle reconnection at its level.
        self._browser._closing = True  # Prevents _listen_loop from calling reconnect

        # Enable core domains
        await self._browser.send("Page.enable")
        await self._browser.send("Runtime.enable")

        # Start listener
        self._browser._listener_task = asyncio.create_task(self._browser._listen_loop())

        self._connected = True
        logger.info("[CDPTab] Connected to tab %s (%s)", self.target_id, self.title or self.url)

    async def disconnect(self) -> None:
        """Disconnect from this tab (does NOT close the browser tab)."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        self._connected = False
        logger.info("[CDPTab] Disconnected from tab %s", self.target_id)

    async def refresh_info(self) -> Dict[str, str]:
        """Refresh title and URL from the live page.

        Returns:
            Dict with 'title' and 'url' keys.
        """
        if not self._connected:
            return {"title": self.title, "url": self.url}

        try:
            self.title = await self.get_title() or self.title
            self.url = await self.get_current_url() or self.url
        except Exception:
            pass
        return {"title": self.title, "url": self.url}

    # -- Delegated CDP operations --------------------------------------------

    async def send(self, method: str, params: Optional[Dict] = None,
                   timeout: Optional[float] = None) -> Dict:
        """Send a raw CDP command via this tab's connection."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.send(method, params, timeout)

    def on(self, event_name: str, callback: Callable[[Dict], Any]) -> None:
        """Register a callback for a CDP event on this tab."""
        if not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        self._browser.on(event_name, callback)

    def off(self, event_name: str, callback: Callable) -> None:
        """Unregister a callback for a CDP event on this tab."""
        if self._browser:
            self._browser.off(event_name, callback)

    async def wait_for_event(self, event_name: str,
                             timeout: Optional[float] = None) -> Dict:
        """Wait for a specific CDP event on this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.wait_for_event(event_name, timeout)

    async def navigate(self, url: str, wait: bool = True,
                       timeout: Optional[float] = None) -> Dict:
        """Navigate this tab to a URL."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        result = await self._browser.navigate(url, wait, timeout)
        self.url = url
        return result

    async def screenshot(self, path: Optional[str] = None,
                         timeout: Optional[float] = None) -> Optional[bytes]:
        """Capture a screenshot of this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.screenshot(path, timeout)

    async def dump_dom(self, timeout: Optional[float] = None) -> Optional[str]:
        """Dump the outerHTML of this tab's page."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.dump_dom(timeout)

    async def eval_js(self, expression: str,
                      timeout: Optional[float] = None) -> Any:
        """Evaluate JavaScript in this tab's page context."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.eval_js(expression, timeout)

    async def click(self, selector: str, timeout: Optional[float] = None) -> bool:
        """Click an element in this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.click(selector, timeout)

    async def type_text(self, selector: str, text: str,
                        timeout: Optional[float] = None) -> bool:
        """Type text into an element in this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.type_text(selector, text, timeout)

    async def wait_for_selector(self, selector: str, poll_interval: float = 0.5,
                                timeout: Optional[float] = None) -> bool:
        """Wait for a CSS selector to appear in this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.wait_for_selector(selector, poll_interval, timeout)

    async def get_current_url(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get the current URL of this tab."""
        if not self._connected or not self._browser:
            return self.url
        return await self._browser.get_current_url(timeout)

    async def get_title(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get the title of this tab's page."""
        if not self._connected or not self._browser:
            return self.title
        return await self._browser.get_title(timeout)

    async def get_cookies(self, timeout: Optional[float] = None) -> List[Dict]:
        """Get cookies for this tab's page."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.get_cookies(timeout)

    # -- Representation ------------------------------------------------------

    def __repr__(self) -> str:
        status = "connected" if self.connected else "disconnected"
        return (
            f"CDPTab(id={self.target_id!r}, title={self.title!r}, "
            f"url={self.url!r}, status={status})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize tab info to a dict (for API responses)."""
        return {
            "target_id": self.target_id,
            "ws_url": self.ws_url,
            "title": self.title,
            "url": self.url,
            "connected": self.connected,
        }


class CDPTabManager:
    """Multi-tab browser orchestrator.

    Manages multiple CDPTab instances, tracks tab lifecycle events,
    and provides a unified interface for tab operations.

    Usage:
        async with CDPTabManager(port=9222) as mgr:
            # Create a new tab
            tab = await mgr.new_tab("https://example.com")

            # List all tabs
            for t in mgr.list_tabs():
                print(t)

            # Switch active tab
            mgr.activate(tab.target_id)

            # Get a specific tab
            tab = mgr.get_tab(target_id)

            # Close a tab
            await mgr.close_tab(target_id)

    Events:
        Register callbacks for tab lifecycle events:
            mgr.on_tab_created(callback)
            mgr.on_tab_destroyed(callback)
            mgr.on_tab_navigated(callback)

        Callback receives a dict with:
            - 'tab': CDPTab instance
            - 'event': event type string
            - 'info': additional event info dict
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        headless: bool = True,
        auto_launch: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        auto_discover_existing: bool = True,
    ):
        self.port = port
        self.headless = headless
        self.auto_launch = auto_launch
        self.timeout = timeout
        self.auto_discover_existing = auto_discover_existing

        self._tabs: Dict[str, CDPTab] = {}  # target_id → CDPTab
        self._active_tab_id: Optional[str] = None
        self._browser_proc: Optional[subprocess.Popen] = None
        self._closing = False

        # Browser-level WebSocket for Target.* events
        self._browser_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._browser_session: Optional[aiohttp.ClientSession] = None
        self._browser_listener_task: Optional[asyncio.Task] = None
        self._browser_req_id = itertools.count(1)
        self._browser_pending: Dict[int, asyncio.Future] = {}

        # Lifecycle event callbacks
        self._tab_created_callbacks: List[Callable] = []
        self._tab_destroyed_callbacks: List[Callable] = []
        self._tab_navigated_callbacks: List[Callable] = []

        # Track fire-and-forget callback tasks for cleanup
        self._callback_tasks: List[asyncio.Task] = []

    # -- Context manager -----------------------------------------------------

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def __del__(self):
        if self._browser_proc or self._browser_session:
            logger.warning(
                "CDPTabManager was not properly closed. "
                "Call 'await mgr.close()' or use 'async with'."
            )

    # -- Properties ----------------------------------------------------------

    @property
    def active_tab(self) -> Optional[CDPTab]:
        """Get the currently active tab."""
        if self._active_tab_id and self._active_tab_id in self._tabs:
            return self._tabs[self._active_tab_id]
        return None

    @property
    def tab_count(self) -> int:
        """Number of tracked tabs."""
        return len(self._tabs)

    @property
    def active_tab_id(self) -> Optional[str]:
        """Get the target ID of the currently active tab."""
        return self._active_tab_id

    # -- Connection management -----------------------------------------------

    async def connect(self) -> None:
        """Connect to the browser and discover existing tabs."""
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for CDPTabManager. Install with: pip install aiohttp")

        # Auto-launch browser if needed
        loop = asyncio.get_running_loop()
        existing_tabs = await loop.run_in_executor(None, list_tabs, self.port)
        if not existing_tabs and self.auto_launch:
            # Run launch_browser in executor to avoid blocking the event loop
            self._browser_proc = await loop.run_in_executor(
                None, launch_browser, self.port, self.headless)

            # Check if browser process is actually alive after launch
            if self._browser_proc and self._browser_proc.poll() is not None:
                # Process already exited — gather diagnostics
                launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                stderr_info = ""
                stderr_log = launch_diag.get("stderr_log", "")
                if stderr_log and os.path.exists(stderr_log):
                    try:
                        with open(stderr_log, "r") as f:
                            stderr_info = f.read().strip()[:1000]
                    except Exception:
                        pass
                rc = self._browser_proc.returncode
                method = launch_diag.get("method", "unknown")
                raise ConnectionError(
                    f"Browser process exited immediately (rc={rc}, method={method}). "
                    f"stderr: {stderr_info[:500] or '(empty)'}. "
                    f"Launch diag: {launch_diag}"
                )

            # Wait for Chromium to initialize and open the debug port
            # Poll every second, up to 15 seconds (increased from 10 for slow systems)
            for attempt in range(15):
                existing_tabs = await loop.run_in_executor(None, list_tabs, self.port)
                if existing_tabs:
                    logger.info("[CDPTabManager] Debug port ready after %ds, %d tab(s)",
                                attempt + 1, len(existing_tabs))
                    break
                # Check if browser process died during startup
                if self._browser_proc and self._browser_proc.poll() is not None:
                    launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                    stderr_info = ""
                    stderr_log = launch_diag.get("stderr_log", "")
                    if stderr_log and os.path.exists(stderr_log):
                        try:
                            with open(stderr_log, "r") as f:
                                stderr_info = f.read().strip()[:1000]
                        except Exception:
                            pass
                    raise ConnectionError(
                        f"Browser crashed during startup (rc={self._browser_proc.returncode}). "
                        f"stderr: {stderr_info[:500] or '(empty)'}. "
                        f"Launch diag: {launch_diag}"
                    )
                await asyncio.sleep(1)
            else:
                # Port never became ready
                if self._browser_proc and self._browser_proc.poll() is None:
                    raise ConnectionError(
                        f"Browser is running (pid={self._browser_proc.pid}) but debug port "
                        f"{self.port} is not responding after 15 seconds. "
                        f"Check if --ozone-platform=headless flag is set."
                    )
                else:
                    raise ConnectionError(
                        f"Browser exited and debug port {self.port} never became ready."
                    )

        # Try to connect browser-level WebSocket for Target events
        await self._connect_browser_ws()

        # Discover and optionally connect existing tabs
        if self.auto_discover_existing:
            for tab_info in existing_tabs:
                if tab_info.get("type") != "page":
                    continue
                target_id = tab_info.get("id", "")
                ws_url = tab_info.get("webSocketDebuggerUrl", "")
                if not target_id or not ws_url:
                    continue
                if target_id in self._tabs:
                    continue  # Already tracked

                tab = CDPTab(
                    target_id=target_id,
                    ws_url=ws_url,
                    port=self.port,
                    timeout=self.timeout,
                    title=tab_info.get("title", ""),
                    url=tab_info.get("url", ""),
                )
                self._tabs[target_id] = tab

                # Set first page tab as active
                if self._active_tab_id is None:
                    self._active_tab_id = target_id

        # Auto-connect to the active tab so operations work immediately
        if self._active_tab_id and self._active_tab_id in self._tabs:
            try:
                await self._tabs[self._active_tab_id].connect()
                logger.info("[CDPTabManager] Auto-connected to active tab %s", self._active_tab_id)
            except Exception as e:
                logger.warning("[CDPTabManager] Failed to auto-connect active tab: %s", e)

        logger.info(
            "[CDPTabManager] Connected. Tracking %d tab(s), active: %s",
            len(self._tabs),
            self._active_tab_id or "none",
        )

    async def _connect_browser_ws(self) -> None:
        """Connect to the browser-level WebSocket for Target domain events.

        Uses the /json/version endpoint to get the browser WebSocket URL,
        which allows monitoring all target (tab) lifecycle events.
        """
        browser_ws_url = await self._get_browser_ws_url()
        if not browser_ws_url:
            logger.warning("[CDPTabManager] No browser-level WS URL found; tab events disabled")
            return

        try:
            self._browser_session = aiohttp.ClientSession()
            self._browser_ws = await self._browser_session.ws_connect(
                browser_ws_url, heartbeat=30
            )

            # Enable Target domain to receive tab lifecycle events
            await self._browser_send("Target.setDiscoverTargets", {"discover": True})

            # Start browser event listener
            self._browser_listener_task = asyncio.create_task(self._browser_listen_loop())

            logger.info("[CDPTabManager] Browser-level WS connected for Target events")
        except Exception as e:
            logger.warning("[CDPTabManager] Failed to connect browser-level WS: %s", e)
            if self._browser_session and not self._browser_session.closed:
                await self._browser_session.close()
            self._browser_session = None
            self._browser_ws = None

    async def _get_browser_ws_url(self) -> Optional[str]:
        """Get the browser-level WebSocket URL from /json/version."""
        url = f"http://127.0.0.1:{self.port}/json/version"
        try:
            loop = asyncio.get_running_loop()
            def _fetch():
                with urllib.request.urlopen(url, timeout=5) as r:
                    return json.loads(r.read().decode())
            info = await loop.run_in_executor(None, _fetch)
            return info.get("webSocketDebuggerUrl")
        except Exception:
            return None

    async def _browser_send(self, method: str, params: Optional[Dict] = None,
                            timeout: Optional[float] = None) -> Dict:
        """Send a CDP command on the browser-level WebSocket."""
        if not self._browser_ws or self._browser_ws.closed:
            raise ConnectionError("Browser WebSocket is not connected")

        msg_id = next(self._browser_req_id)
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._browser_pending[msg_id] = future

        await self._browser_ws.send_json(msg)
        logger.debug("[CDPTabManager:BrowserWS] -> %s %s (id=%d)", method, params or "", msg_id)

        effective_timeout = timeout or self.timeout
        try:
            return await asyncio.wait_for(future, effective_timeout)
        except asyncio.TimeoutError:
            self._browser_pending.pop(msg_id, None)
            raise

    async def _browser_listen_loop(self) -> None:
        """Background task: listen for browser-level CDP events (Target.*)."""
        try:
            async for msg in self._browser_ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    # Handle responses to our browser-level commands
                    msg_id = data.get("id")
                    if msg_id and msg_id in self._browser_pending:
                        future = self._browser_pending.pop(msg_id)
                        if not future.done():
                            future.set_result(data)
                        continue

                    # Handle Target domain events
                    method = data.get("method", "")
                    params = data.get("params", {})

                    if method == "Target.targetCreated":
                        await self._handle_target_created(params)
                    elif method == "Target.targetDestroyed":
                        await self._handle_target_destroyed(params)
                    elif method == "Target.targetInfoChanged":
                        await self._handle_target_info_changed(params)

                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[CDPTabManager:BrowserWS] Listener error: %s", e)

    async def _handle_target_created(self, params: Dict) -> None:
        """Handle Target.targetCreated event."""
        target_info = params.get("targetInfo", {})
        target_id = target_info.get("targetId", "")
        target_type = target_info.get("type", "")

        # Only track page targets (tabs)
        if target_type != "page":
            return

        if target_id in self._tabs:
            return  # Already tracked

        # Get the WebSocket URL for this new tab
        ws_url = await self._get_ws_url_for_target(target_id)
        if not ws_url:
            # Fallback: try from tab list (non-blocking)
            loop = asyncio.get_running_loop()
            tabs = await loop.run_in_executor(None, list_tabs, self.port)
            for tab_info in tabs:
                if tab_info.get("id") == target_id:
                    ws_url = tab_info.get("webSocketDebuggerUrl", "")
                    break

        if not ws_url:
            logger.warning("[CDPTabManager] No WS URL for new target %s", target_id)
            return

        tab = CDPTab(
            target_id=target_id,
            ws_url=ws_url,
            port=self.port,
            timeout=self.timeout,
            title=target_info.get("title", ""),
            url=target_info.get("url", ""),
        )
        self._tabs[target_id] = tab

        # Set as active if this is the first tab
        if self._active_tab_id is None:
            self._active_tab_id = target_id

        logger.info("[CDPTabManager] Tab created: %s (%s)", target_id, tab.title or tab.url)

        # Fire callbacks
        for cb in self._tab_created_callbacks:
            try:
                result = cb({"tab": tab, "event": "created", "info": target_info})
                if asyncio.iscoroutine(result):
                    task = asyncio.create_task(result)
                    task.add_done_callback(self._log_callback_error)
                    self._callback_tasks.append(task)
            except Exception as e:
                logger.error("[CDPTabManager] tab_created callback error: %s", e)

    async def _handle_target_destroyed(self, params: Dict) -> None:
        """Handle Target.targetDestroyed event."""
        target_id = params.get("targetId", "")

        tab = self._tabs.pop(target_id, None)
        if tab is None:
            return

        # Disconnect the tab's CDP connection
        if tab.connected:
            await tab.disconnect()

        # Update active tab if needed
        if self._active_tab_id == target_id:
            self._active_tab_id = None
            # Activate another tab if available
            if self._tabs:
                self._active_tab_id = next(iter(self._tabs))

        logger.info("[CDPTabManager] Tab destroyed: %s", target_id)

        # Fire callbacks
        for cb in self._tab_destroyed_callbacks:
            try:
                result = cb({"tab": tab, "event": "destroyed", "info": {"targetId": target_id}})
                if asyncio.iscoroutine(result):
                    task = asyncio.create_task(result)
                    task.add_done_callback(self._log_callback_error)
                    self._callback_tasks.append(task)
            except Exception as e:
                logger.error("[CDPTabManager] tab_destroyed callback error: %s", e)

    async def _handle_target_info_changed(self, params: Dict) -> None:
        """Handle Target.targetInfoChanged event."""
        target_info = params.get("targetInfo", {})
        target_id = target_info.get("targetId", "")

        tab = self._tabs.get(target_id)
        if tab is None:
            return

        old_url = tab.url
        tab.title = target_info.get("title", tab.title)
        tab.url = target_info.get("url", tab.url)

        # Fire navigated callback if URL changed
        if old_url != tab.url:
            for cb in self._tab_navigated_callbacks:
                try:
                    result = cb({
                        "tab": tab,
                        "event": "navigated",
                        "info": {"old_url": old_url, "new_url": tab.url},
                    })
                    if asyncio.iscoroutine(result):
                        task = asyncio.create_task(result)
                        task.add_done_callback(self._log_callback_error)
                        self._callback_tasks.append(task)
                except Exception as e:
                    logger.error("[CDPTabManager] tab_navigated callback error: %s", e)

    async def _get_ws_url_for_target(self, target_id: str) -> Optional[str]:
        """Get the WebSocket URL for a target ID.

        Uses Target.getTargetInfo (non-session-creating) to verify the target
        exists, then constructs the WS URL. Falls back to HTTP /json/list.
        """
        # Try via CDP Target.getTargetInfo (does NOT create a session)
        if self._browser_ws and not self._browser_ws.closed:
            try:
                res = await self._browser_send(
                    "Target.getTargetInfo",
                    {"targetId": target_id},
                )
                if res and "result" in res:
                    # Target confirmed to exist — construct WS URL
                    return f"ws://127.0.0.1:{self.port}/devtools/page/{target_id}"
            except Exception:
                pass

        # Fallback: search in HTTP tab list
        loop = asyncio.get_running_loop()
        tabs = await loop.run_in_executor(None, list_tabs, self.port)
        for tab_info in tabs:
            if tab_info.get("id") == target_id:
                return tab_info.get("webSocketDebuggerUrl")

        return None

    # -- Tab operations ------------------------------------------------------

    async def new_tab(self, url: str = "about:blank", activate: bool = True) -> CDPTab:
        """Create a new browser tab and return a CDPTab for it.

        Args:
            url: Initial URL for the new tab (default: about:blank)
            activate: If True, set the new tab as the active tab (default: True)

        Returns:
            CDPTab instance for the new tab

        Raises:
            ConnectionError: if tab creation fails
        """
        # Use HTTP endpoint to create the tab
        ws_url = get_new_tab_url(self.port)
        if not ws_url:
            raise ConnectionError("Failed to create new tab")

        # Extract target ID from WebSocket URL
        # Format: ws://127.0.0.1:9222/devtools/page/{TARGET_ID}
        target_id = ws_url.rstrip("/").split("/")[-1]

        # Create CDPTab
        tab = CDPTab(
            target_id=target_id,
            ws_url=ws_url,
            port=self.port,
            timeout=self.timeout,
            url=url,
        )

        # Register in tab map BEFORE connecting, so _handle_target_created's
        # early-return on "already tracked" prevents duplicate registration
        self._tabs[target_id] = tab

        # Connect to the new tab (with timeout)
        await asyncio.wait_for(tab.connect(), timeout=self.timeout)

        # Navigate if URL specified
        if url and url != "about:blank":
            await tab.navigate(url, wait=True)

        if activate:
            self._active_tab_id = target_id

        logger.info("[CDPTabManager] New tab created and connected: %s → %s", target_id, url)
        return tab

    async def close_tab(self, target_id: str) -> bool:
        """Close a browser tab and clean up its CDPTab connection.

        Args:
            target_id: The target ID of the tab to close

        Returns:
            True if the tab was closed successfully
        """
        tab = self._tabs.get(target_id)
        if tab is None:
            # Try closing via HTTP anyway
            return close_tab(target_id, self.port)

        # Disconnect our CDP connection first
        if tab.connected:
            await tab.disconnect()

        # Close the browser tab via HTTP
        success = close_tab(target_id, self.port)

        # Remove from tracking
        self._tabs.pop(target_id, None)

        # Update active tab
        if self._active_tab_id == target_id:
            self._active_tab_id = None
            if self._tabs:
                self._active_tab_id = next(iter(self._tabs))

        logger.info("[CDPTabManager] Tab closed: %s (success=%s)", target_id, success)
        return success

    def activate(self, target_id: str) -> bool:
        """Set a tab as the active tab.

        Args:
            target_id: The target ID of the tab to activate

        Returns:
            True if the tab was found and activated
        """
        if target_id in self._tabs:
            self._active_tab_id = target_id
            logger.info("[CDPTabManager] Activated tab: %s", target_id)
            return True
        logger.warning("[CDPTabManager] Cannot activate unknown tab: %s", target_id)
        return False

    def get_tab(self, target_id: str) -> Optional[CDPTab]:
        """Get a CDPTab by target ID."""
        return self._tabs.get(target_id)

    def get_tab_by_url(self, url: str) -> Optional[CDPTab]:
        """Find a tab by its URL (exact match)."""
        for tab in self._tabs.values():
            if tab.url == url:
                return tab
        return None

    def get_tab_by_title(self, title: str) -> Optional[CDPTab]:
        """Find a tab by its title (exact match)."""
        for tab in self._tabs.values():
            if tab.title == title:
                return tab
        return None

    def list_tabs(self) -> List[CDPTab]:
        """List all tracked tabs."""
        return list(self._tabs.values())

    async def connect_tab(self, target_id: str) -> CDPTab:
        """Connect to a tracked tab that isn't connected yet.

        Useful when auto_discover_existing=False or for reconnecting.

        Args:
            target_id: The target ID of the tab

        Returns:
            The connected CDPTab

        Raises:
            KeyError: if target_id is not tracked
            ConnectionError: if connection fails
        """
        tab = self._tabs.get(target_id)
        if tab is None:
            raise KeyError(f"Tab {target_id} is not tracked")
        if not tab.connected:
            await asyncio.wait_for(tab.connect(), timeout=self.timeout)
        return tab

    async def disconnect_tab(self, target_id: str) -> None:
        """Disconnect from a tab without closing it in the browser.

        Args:
            target_id: The target ID of the tab
        """
        tab = self._tabs.get(target_id)
        if tab and tab.connected:
            await tab.disconnect()

    async def sync_tabs(self) -> List[CDPTab]:
        """Synchronize tracked tabs with the browser's actual tab list.

        Discovers new tabs, removes closed ones. Useful if the
        browser-level WebSocket is unavailable and tab events were missed.

        Returns:
            Updated list of all tracked tabs
        """
        loop = asyncio.get_running_loop()
        current_tabs = await loop.run_in_executor(None, list_tabs, self.port)
        current_ids = set()

        for tab_info in current_tabs:
            if tab_info.get("type") != "page":
                continue
            target_id = tab_info.get("id", "")
            ws_url = tab_info.get("webSocketDebuggerUrl", "")
            if not target_id:
                continue

            current_ids.add(target_id)

            if target_id in self._tabs:
                # Update existing tab metadata
                tab = self._tabs[target_id]
                tab.title = tab_info.get("title", tab.title)
                tab.url = tab_info.get("url", tab.url)
                if ws_url:
                    tab.ws_url = ws_url
            else:
                # New tab discovered
                if not ws_url:
                    continue
                tab = CDPTab(
                    target_id=target_id,
                    ws_url=ws_url,
                    port=self.port,
                    timeout=self.timeout,
                    title=tab_info.get("title", ""),
                    url=tab_info.get("url", ""),
                )
                self._tabs[target_id] = tab

        # Remove tabs that no longer exist
        removed_ids = set(self._tabs.keys()) - current_ids
        for target_id in removed_ids:
            tab = self._tabs.pop(target_id)
            if tab.connected:
                await tab.disconnect()
            if self._active_tab_id == target_id:
                self._active_tab_id = next(iter(self._tabs)) if self._tabs else None

        if removed_ids:
            logger.info("[CDPTabManager] Sync removed %d stale tab(s)", len(removed_ids))

        return self.list_tabs()

    # -- Lifecycle event callbacks -------------------------------------------

    def on_tab_created(self, callback: Callable) -> None:
        """Register a callback for tab creation events.

        Callback receives: {"tab": CDPTab, "event": "created", "info": dict}
        """
        self._tab_created_callbacks.append(callback)

    def on_tab_destroyed(self, callback: Callable) -> None:
        """Register a callback for tab destruction events.

        Callback receives: {"tab": CDPTab, "event": "destroyed", "info": dict}
        """
        self._tab_destroyed_callbacks.append(callback)

    def on_tab_navigated(self, callback: Callable) -> None:
        """Register a callback for tab navigation events.

        Callback receives: {"tab": CDPTab, "event": "navigated", "info": dict}
        """
        self._tab_navigated_callbacks.append(callback)

    def off_tab_created(self, callback: Callable) -> None:
        """Unregister a tab creation callback."""
        if callback in self._tab_created_callbacks:
            self._tab_created_callbacks.remove(callback)

    def off_tab_destroyed(self, callback: Callable) -> None:
        """Unregister a tab destruction callback."""
        if callback in self._tab_destroyed_callbacks:
            self._tab_destroyed_callbacks.remove(callback)

    def off_tab_navigated(self, callback: Callable) -> None:
        """Unregister a tab navigation callback."""
        if callback in self._tab_navigated_callbacks:
            self._tab_navigated_callbacks.remove(callback)

    @staticmethod
    def _log_callback_error(task: asyncio.Task) -> None:
        """Log exceptions from fire-and-forget callback tasks."""
        if not task.cancelled():
            try:
                task.exception()
            except Exception as e:
                logger.error("[CDPTabManager] Async callback task error: %s", e)

    # -- Cleanup -------------------------------------------------------------

    async def close(self) -> None:
        """Close all tab connections and the browser-level WebSocket."""
        self._closing = True

        # Cancel pending browser-level futures so callers don't hang
        for msg_id, future in list(self._browser_pending.items()):
            if not future.done():
                future.cancel()
        self._browser_pending.clear()

        # Cancel orphaned callback tasks
        for task in self._callback_tasks:
            if not task.done():
                task.cancel()
        self._callback_tasks.clear()

        # Disconnect all tracked tabs
        for tab in list(self._tabs.values()):
            if tab.connected:
                try:
                    await tab.disconnect()
                except Exception as e:
                    logger.warning("[CDPTabManager] Error disconnecting tab %s: %s", tab.target_id, e)
        self._tabs.clear()

        # Close browser-level WebSocket
        if self._browser_listener_task:
            self._browser_listener_task.cancel()
            try:
                await self._browser_listener_task
            except asyncio.CancelledError:
                pass

        if self._browser_ws and not self._browser_ws.closed:
            await self._browser_ws.close()
        if self._browser_session and not self._browser_session.closed:
            await self._browser_session.close()

        # Terminate browser if we launched it
        if self._browser_proc:
            self._browser_proc.terminate()
            try:
                self._browser_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._browser_proc.kill()

        logger.info("[CDPTabManager] Closed")

    # -- Representation ------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"CDPTabManager(port={self.port}, tabs={len(self._tabs)}, "
            f"active={self._active_tab_id!r})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manager state to a dict (for API responses)."""
        return {
            "port": self.port,
            "tab_count": len(self._tabs),
            "active_tab_id": self._active_tab_id,
            "tabs": [tab.to_dict() for tab in self._tabs.values()],
        }


# ---------------------------------------------------------------------------
# Synchronous fallback (raw socket, no aiohttp needed)
# ---------------------------------------------------------------------------
class SyncCDPBrowser:
    """Synchronous CDP browser using raw socket WebSocket.
    Used as a fallback when aiohttp is not available.

    This preserves the original functionality of cdp_browser.py
    while adding incremental request IDs and basic timeouts.
    """

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.sock = None
        self._req_id = itertools.count(1)

    def connect(self) -> None:
        ws_url = get_websocket_url(self.port)
        if not ws_url:
            launch_browser(self.port)
            ws_url = get_websocket_url(self.port)
        if not ws_url:
            raise ConnectionError(f"Cannot connect to CDP port {self.port}")
        self.sock = self._perform_handshake(ws_url)
        # Enable core domains (backward compat: always enable on connect)
        self.call("Page.enable")
        self.call("Runtime.enable")

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def _perform_handshake(self, ws_url: str):
        import urllib.parse as up
        import socket as _socket
        import struct as _struct

        parsed = up.urlparse(ws_url)
        host = parsed.hostname
        port = parsed.port or 9222
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query

        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))

        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode())

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(1)
            if not chunk:
                break
            resp += chunk
        return sock

    @staticmethod
    def _send_frame(sock, data: str) -> None:
        import struct as _struct
        import os as _os

        payload = data.encode("utf-8")
        length = len(payload)
        mask = _os.urandom(4)
        header = bytearray([0x81])
        if length < 126:
            header.append(length | 0x80)
        elif length <= 65535:
            header.append(126 | 0x80)
            header.extend(_struct.pack("!H", length))
        else:
            header.append(127 | 0x80)
            header.extend(_struct.pack("!Q", length))
        header.extend(mask)

        masked = bytearray(length)
        for i in range(length):
            masked[i] = payload[i] ^ mask[i % 4]
        sock.sendall(header + masked)

    @staticmethod
    def _recv_frame(sock) -> Optional[str]:
        import struct as _struct

        head = sock.recv(2)
        if not head or len(head) < 2:
            return None
        payload_len = head[1] & 0x7F
        if payload_len == 126:
            ext = sock.recv(2)
            payload_len = _struct.unpack("!H", ext)[0]
        elif payload_len == 127:
            ext = sock.recv(8)
            payload_len = _struct.unpack("!Q", ext)[0]
        # Read full payload (handle partial reads)
        data = b""
        while len(data) < payload_len:
            chunk = sock.recv(payload_len - len(data))
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8", errors="ignore")

    def call(self, method: str, params: Optional[Dict] = None) -> Optional[Dict]:
        msg_id = next(self._req_id)
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        self._send_frame(self.sock, json.dumps(msg))

        while True:
            frame = self._recv_frame(self.sock)
            if not frame:
                break
            try:
                data = json.loads(frame)
                if data.get("id") == msg_id:
                    return data
                # Events are silently ignored in sync mode
            except json.JSONDecodeError:
                continue
        return None

    def navigate(self, url: str) -> None:
        self.call("Page.navigate", {"url": url})
        time.sleep(3)

    def screenshot(self, path: str = "screenshot_cdp.png") -> bool:
        res = self.call("Page.captureScreenshot")
        if res and "result" in res and "data" in res["result"]:
            with open(path, "wb") as f:
                f.write(base64.b64decode(res["result"]["data"]))
            return True
        return False

    def dump_dom(self) -> Optional[str]:
        res = self.call("Runtime.evaluate", {"expression": "document.documentElement.outerHTML"})
        if res and "result" in res and "result" in res["result"]:
            return res["result"]["result"].get("value")
        return None

    def eval_js(self, expression: str) -> Optional[str]:
        res = self.call("Runtime.evaluate", {"expression": expression})
        if res and "result" in res and "result" in res["result"]:
            return json.dumps(res["result"]["result"], indent=2, ensure_ascii=False)
        return None


# ---------------------------------------------------------------------------
# CLI entry point (backward compatible)
# ---------------------------------------------------------------------------
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


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Network monitoring and interception
# ---------------------------------------------------------------------------

class NetworkRequest:
    """Represents a single network request/response cycle.

    Accumulates data as CDP events arrive:
      requestWillBeSent → responseReceived → loadingFinished / loadingFailed
    """

    __slots__ = (
        "request_id", "url", "method", "headers", "post_data",
        "resource_type", "frame_id", "timestamp", "wall_time",
        "redirect_count", "redirect_response", "initiator",
        "response_status", "response_status_text", "response_headers",
        "response_mimeType", "response_remote_ip", "response_remote_port",
        "response_protocol", "response_security_details",
        "encoded_data_length", "decoded_body_length",
        "error_text", "error_canceled", "error_blocked_reason",
        "finished", "finish_time",
    )

    def __init__(self, request_id: str, **kwargs):
        self.request_id = request_id
        self.url = kwargs.get("url", "")
        self.method = kwargs.get("method", "")
        self.headers = kwargs.get("headers", {})
        self.post_data = kwargs.get("postData")
        self.resource_type = kwargs.get("resourceType", "")
        self.frame_id = kwargs.get("frameId", "")
        self.timestamp = kwargs.get("timestamp", 0)
        self.wall_time = kwargs.get("wallTime", 0)
        self.redirect_count = kwargs.get("redirectCount", 0)
        self.redirect_response = kwargs.get("redirectResponse")
        self.initiator = kwargs.get("initiator", {})
        # Response fields (filled later)
        self.response_status = None
        self.response_status_text = None
        self.response_headers = None
        self.response_mimeType = None
        self.response_remote_ip = None
        self.response_remote_port = None
        self.response_protocol = None
        self.response_security_details = None
        self.encoded_data_length = None
        self.decoded_body_length = None
        # Error fields
        self.error_text = None
        self.error_canceled = False
        self.error_blocked_reason = None
        # State
        self.finished = False
        self.finish_time = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict (for API responses / logging)."""
        return {k: getattr(self, k) for k in self.__slots__ if getattr(self, k) is not None}


class CDPNetworkMonitor:
    """Passive network traffic monitor using CDP Network domain.

    Records all requests and responses without modifying them.
    Useful for debugging, analytics, and performance profiling.

    Usage:
        async with CDPBrowser() as browser:
            monitor = CDPNetworkMonitor(browser)
            await monitor.start()
            await browser.navigate("https://example.com")
            requests = monitor.get_requests()
            har = monitor.export_har()
            await monitor.stop()
    """

    def __init__(self, browser: CDPBrowser, max_entries: int = 1000):
        self._browser = browser
        self._max_entries = max_entries
        self._requests: Dict[str, NetworkRequest] = {}
        self._finished: List[NetworkRequest] = []
        self._active = False

    # -- Lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Enable network monitoring and register event handlers."""
        if self._active:
            return
        await self._browser.send("Network.enable")
        self._browser.on("Network.requestWillBeSent", self._on_request_will_be_sent)
        self._browser.on("Network.responseReceived", self._on_response_received)
        self._browser.on("Network.loadingFinished", self._on_loading_finished)
        self._browser.on("Network.loadingFailed", self._on_loading_failed)
        self._active = True
        logger.info("[CDPNetworkMonitor] Monitoring started")

    async def stop(self) -> None:
        """Disable network monitoring and unregister event handlers."""
        if not self._active:
            return
        self._browser.off("Network.requestWillBeSent", self._on_request_will_be_sent)
        self._browser.off("Network.responseReceived", self._on_response_received)
        self._browser.off("Network.loadingFinished", self._on_loading_finished)
        self._browser.off("Network.loadingFailed", self._on_loading_failed)
        # Note: We do NOT call Network.disable here because other consumers
        # (e.g., CDPBrowser.get_cookies) may still need the Network domain.
        # Handlers are unregistered so we stop receiving events.
        self._active = False
        logger.info("[CDPNetworkMonitor] Monitoring stopped")

    @property
    def active(self) -> bool:
        """Whether monitoring is currently active."""
        return self._active

    # -- Event handlers ------------------------------------------------------

    def _on_request_will_be_sent(self, params: Dict) -> None:
        """Handle Network.requestWillBeSent."""
        request_id = params.get("requestId", "")
        request_data = params.get("request", {})
        # If this is a redirect, finalize the previous request
        redirect_response = params.get("redirectResponse")
        if redirect_response and request_id in self._requests:
            prev = self._requests[request_id]
            prev.response_status = redirect_response.get("status")
            prev.response_status_text = redirect_response.get("statusText", "")
            prev.response_headers = redirect_response.get("headers", {})
            prev.response_mimeType = redirect_response.get("mimeType", "")
            prev.redirect_count += 1
            self._finalize_request(request_id, params.get("timestamp"))

        # Create new request entry (redirect_response belongs to prev hop, not this one)
        req = NetworkRequest(
            request_id=request_id,
            url=request_data.get("url", ""),
            method=request_data.get("method", ""),
            headers=request_data.get("headers", {}),
            postData=request_data.get("postData"),
            resourceType=params.get("type", ""),
            frameId=params.get("frameId", ""),
            timestamp=params.get("timestamp", 0),
            wallTime=params.get("wallTime", 0),
            redirectCount=0,
            redirectResponse=None,
            initiator=params.get("initiator", {}),
        )
        self._requests[request_id] = req

    def _on_response_received(self, params: Dict) -> None:
        """Handle Network.responseReceived."""
        request_id = params.get("requestId", "")
        response = params.get("response", {})
        req = self._requests.get(request_id)
        if req:
            req.response_status = response.get("status")
            req.response_status_text = response.get("statusText", "")
            req.response_headers = response.get("headers", {})
            req.response_mimeType = response.get("mimeType", "")
            req.response_remote_ip = response.get("remoteIPAddress")
            req.response_remote_port = response.get("remotePort")
            req.response_protocol = response.get("protocol", "")
            req.response_security_details = response.get("securityDetails")

    def _on_loading_finished(self, params: Dict) -> None:
        """Handle Network.loadingFinished."""
        request_id = params.get("requestId", "")
        req = self._requests.get(request_id)
        if req:
            req.encoded_data_length = params.get("encodedDataLength")
            ddl = params.get("decodedDataLength")
            req.decoded_body_length = ddl if ddl is not None else params.get("encodedDataLength")
            self._finalize_request(request_id, params.get("timestamp"))

    def _on_loading_failed(self, params: Dict) -> None:
        """Handle Network.loadingFailed."""
        request_id = params.get("requestId", "")
        req = self._requests.get(request_id)
        if req:
            req.error_text = params.get("errorText", "")
            req.error_canceled = params.get("canceled", False)
            req.error_blocked_reason = params.get("blockedReason")
            self._finalize_request(request_id, params.get("timestamp"))

    def _finalize_request(self, request_id: str, finish_timestamp: float = None) -> None:
        """Move a request from active to finished list."""
        req = self._requests.pop(request_id, None)
        if req:
            req.finished = True
            req.finish_time = finish_timestamp if finish_timestamp is not None else req.timestamp
            self._finished.append(req)
            # Trim if over max
            while len(self._finished) > self._max_entries:
                self._finished.pop(0)

    # -- Query methods -------------------------------------------------------

    def get_requests(self, url_filter: Optional[str] = None,
                     resource_type: Optional[str] = None) -> List[NetworkRequest]:
        """Get finished requests, optionally filtered.

        Args:
            url_filter: Only return requests whose URL contains this substring
            resource_type: Only return requests of this resource type (e.g., "Document", "Script")

        Returns:
            List of matching NetworkRequest objects
        """
        results = self._finished
        if url_filter:
            results = [r for r in results if url_filter in r.url]
        if resource_type:
            results = [r for r in results if r.resource_type == resource_type]
        return results

    def get_active_requests(self) -> List[NetworkRequest]:
        """Get currently in-flight requests."""
        return list(self._requests.values())

    def get_request_by_id(self, request_id: str) -> Optional[NetworkRequest]:
        """Get a specific request by its ID."""
        return self._requests.get(request_id) or next(
            (r for r in self._finished if r.request_id == request_id), None
        )

    @property
    def total_requests(self) -> int:
        """Total number of finished requests."""
        return len(self._finished)

    @property
    def active_count(self) -> int:
        """Number of currently in-flight requests."""
        return len(self._requests)

    def clear(self) -> None:
        """Clear all recorded requests."""
        self._requests.clear()
        self._finished.clear()

    def export_har(self) -> Dict[str, Any]:
        """Export recorded requests in HAR-like format.

        Returns:
            Dict in HAR 1.2-like structure for interoperability.
        """
        entries = []
        for req in self._finished:
            # Convert wall_time (epoch float) to ISO 8601
            started_dt = ""
            if req.wall_time:
                from datetime import datetime, timezone
                try:
                    started_dt = datetime.fromtimestamp(req.wall_time, tz=timezone.utc).isoformat()
                except Exception:
                    started_dt = str(req.wall_time)

            # Compute elapsed time in milliseconds
            elapsed_ms = 0
            if req.finish_time is not None and req.timestamp:
                elapsed_ms = round((req.finish_time - req.timestamp) * 1000)

            entry = {
                "startedDateTime": started_dt,
                "request": {
                    "method": req.method,
                    "url": req.url,
                    "headers": req.headers,
                },
                "response": {
                    "status": req.response_status,
                    "statusText": req.response_status_text,
                    "headers": req.response_headers,
                    "mimeType": req.response_mimeType,
                    "remoteIP": req.response_remote_ip,
                    "remotePort": req.response_remote_port,
                },
                "time": elapsed_ms,
            }
            if req.error_text:
                entry["_error"] = req.error_text
            entries.append(entry)

        return {
            "log": {
                "version": "1.2",
                "creator": {"name": "cdp_browser", "version": "1.0"},
                "entries": entries,
            }
        }


class InterceptRule:
    """A single interception rule for CDPNetworkInterceptor.

    Matches requests by URL pattern and/or resource type,
    and applies an action: block, redirect, modify headers, or mock response.
    """

    def __init__(
        self,
        name: str = "",
        url_pattern: Optional[str] = None,
        resource_type: Optional[str] = None,
        action: str = "block",  # block, redirect, modify_headers, mock
        redirect_url: Optional[str] = None,
        modify_request_headers: Optional[Dict[str, str]] = None,
        modify_response_headers: Optional[Dict[str, str]] = None,
        remove_request_headers: Optional[List[str]] = None,
        remove_response_headers: Optional[List[str]] = None,
        mock_status: int = 200,
        mock_headers: Optional[Dict[str, str]] = None,
        mock_body: Optional[str] = None,
        mock_content_type: str = "text/plain",
        enabled: bool = True,
    ):
        self.name = name
        self.url_pattern = url_pattern
        self.resource_type = resource_type
        if action not in ("block", "redirect", "modify_headers", "mock"):
            raise ValueError(f"Invalid action {action!r}. Must be one of: block, redirect, modify_headers, mock")
        self.action = action
        self.redirect_url = redirect_url
        self.modify_request_headers = modify_request_headers or {}
        self.modify_response_headers = modify_response_headers or {}
        self.remove_request_headers = remove_request_headers or []
        self.remove_response_headers = remove_response_headers or []
        self.mock_status = mock_status
        self.mock_headers = {"Content-Type": mock_content_type}
        if mock_headers:
            self.mock_headers.update(mock_headers)
        self.mock_body = mock_body
        self.enabled = enabled
        self._hit_count = 0

    def matches(self, url: str, resource_type: str) -> bool:
        """Check if this rule matches the given request."""
        if not self.enabled:
            return False
        if self.url_pattern and self.url_pattern not in url:
            return False
        if self.resource_type and self.resource_type != resource_type:
            return False
        return True

    def record_hit(self) -> None:
        """Record that this rule matched a request."""
        self._hit_count += 1

    @property
    def hit_count(self) -> int:
        """Number of times this rule has been triggered."""
        return self._hit_count

    def to_dict(self) -> Dict[str, Any]:
        """Serialize rule to a dict."""
        return {
            "name": self.name,
            "url_pattern": self.url_pattern,
            "resource_type": self.resource_type,
            "action": self.action,
            "enabled": self.enabled,
            "hit_count": self._hit_count,
        }


class CDPNetworkInterceptor:
    """Active network traffic interceptor using CDP Fetch domain.

    Intercepts, modifies, blocks, or mocks network requests based on rules.

    Usage:
        async with CDPBrowser() as browser:
            interceptor = CDPNetworkInterceptor(browser)
            await interceptor.start()

            # Block all image requests
            interceptor.add_rule(InterceptRule(
                name="block-images",
                resource_type="Image",
                action="block",
            ))

            # Redirect API calls to mock server
            interceptor.add_rule(InterceptRule(
                name="redirect-api",
                url_pattern="/api/",
                action="redirect",
                redirect_url="http://mock-server:8080",
            ))

            # Mock a specific endpoint
            interceptor.add_rule(InterceptRule(
                name="mock-health",
                url_pattern="/health",
                action="mock",
                mock_status=200,
                mock_body='{"status":"ok"}',
                mock_content_type="application/json",
            ))

            await browser.navigate("https://example.com")
            await interceptor.stop()
    """

    _VALID_ACTIONS = {"block", "redirect", "modify_headers", "mock"}

    def __init__(self, browser: CDPBrowser):
        self._browser = browser
        self._rules: List[InterceptRule] = []
        self._active = False
        self._paused_requests: Dict[str, Dict] = {}  # requestId → paused event params
        self._handler_tasks: set = set()  # Track in-flight handler tasks

    # -- Lifecycle -----------------------------------------------------------

    async def start(self, patterns: Optional[List[Dict]] = None) -> None:
        """Enable network interception.

        Args:
            patterns: Optional list of Fetch pattern dicts to pass to Fetch.enable.
                     If None, intercepts all requests.
                     Example: [{"urlPattern": "*://example.com/*"}]
        """
        if self._active:
            return

        # Default: intercept everything
        if patterns is None:
            patterns = [{"urlPattern": "*"}]

        await self._browser.send("Fetch.enable", {
            "patterns": patterns,
            "handleAuthRequests": False,
        })

        self._browser.on("Fetch.requestPaused", self._on_request_paused)
        self._active = True
        logger.info("[CDPNetworkInterceptor] Interception started with %d pattern(s)", len(patterns))

    async def stop(self) -> None:
        """Disable network interception."""
        if not self._active:
            return

        self._browser.off("Fetch.requestPaused", self._on_request_paused)

        # Resume any paused requests before disabling
        for request_id, params in list(self._paused_requests.items()):
            try:
                await self._browser.send("Fetch.continueRequest", {"requestId": request_id})
            except Exception:
                pass
        self._paused_requests.clear()

        try:
            await self._browser.send("Fetch.disable")
        except Exception:
            pass

        self._active = False
        logger.info("[CDPNetworkInterceptor] Interception stopped")

    @property
    def active(self) -> bool:
        """Whether interception is currently active."""
        return self._active

    # -- Rule management -----------------------------------------------------

    def add_rule(self, rule: InterceptRule) -> None:
        """Add an interception rule."""
        self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name. Returns True if found and removed."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    def get_rules(self) -> List[InterceptRule]:
        """Get all rules."""
        return list(self._rules)

    def clear_rules(self) -> None:
        """Remove all rules."""
        self._rules.clear()

    # -- Event handler -------------------------------------------------------

    async def _on_request_paused(self, params: Dict) -> None:
        """Handle Fetch.requestPaused — apply rules and decide action."""
        request_id = params.get("requestId", "")
        url = params.get("request", {}).get("url", "")
        resource_type = params.get("resourceType", "")

        # Find matching rule (first match wins)
        matched_rule = None
        for rule in self._rules:
            if rule.matches(url, resource_type):
                matched_rule = rule
                break

        if matched_rule is None:
            # No rule matched — continue the request normally
            try:
                await self._browser.send("Fetch.continueRequest", {"requestId": request_id})
            except Exception as e:
                logger.error("[CDPNetworkInterceptor] Failed to continue request %s: %s", request_id, e)
            return

        # Track paused request for safety-resume in stop()
        self._paused_requests[request_id] = params

        matched_rule.record_hit()
        logger.info(
            "[CDPNetworkInterceptor] Rule '%s' matched: %s %s → %s",
            matched_rule.name, params.get("request", {}).get("method", "?"),
            url[:80], matched_rule.action,
        )

        try:
            if matched_rule.action == "block":
                await self._browser.send("Fetch.failRequest", {
                    "requestId": request_id,
                    "reason": "BlockedByClient",
                })

            elif matched_rule.action == "redirect":
                # Use continueRequest with url for true network-level redirect
                await self._browser.send("Fetch.continueRequest", {
                    "requestId": request_id,
                    "url": matched_rule.redirect_url,
                })

            elif matched_rule.action == "modify_headers":
                headers = params.get("request", {}).get("headers", {})
                # Remove specified headers
                for h in matched_rule.remove_request_headers:
                    headers.pop(h, None)
                # Add/modify headers
                headers.update(matched_rule.modify_request_headers)
                # Build CDP header list
                header_list = [{"name": k, "value": v} for k, v in headers.items()]
                await self._browser.send("Fetch.continueRequest", {
                    "requestId": request_id,
                    "headers": header_list,
                })

            elif matched_rule.action == "mock":
                body_b64 = ""
                if matched_rule.mock_body:
                    body_b64 = base64.b64encode(
                        matched_rule.mock_body.encode("utf-8")
                    ).decode("ascii")
                header_list = [
                    {"name": k, "value": v}
                    for k, v in matched_rule.mock_headers.items()
                ]
                await self._browser.send("Fetch.fulfillRequest", {
                    "requestId": request_id,
                    "responseCode": matched_rule.mock_status,
                    "responseHeaders": header_list,
                    "body": body_b64,
                })

            else:
                # Unknown action — continue normally (should not happen due to validation)
                logger.warning("[CDPNetworkInterceptor] Unknown action '%s', continuing request", matched_rule.action)
                await self._browser.send("Fetch.continueRequest", {"requestId": request_id})

            # Remove from paused tracking after successful handling
            self._paused_requests.pop(request_id, None)

        except Exception as e:
            logger.error("[CDPNetworkInterceptor] Error handling paused request %s: %s", request_id, e)
            # Try to continue the request to avoid it hanging forever
            try:
                await self._browser.send("Fetch.continueRequest", {"requestId": request_id})
                self._paused_requests.pop(request_id, None)
            except Exception:
                pass

    # -- Convenience methods -------------------------------------------------

    def block_urls(self, *url_patterns: str, name: str = "") -> None:
        """Block requests matching any of the URL patterns.

        Args:
            url_patterns: Substrings to match in request URLs
            name: Optional name for the rule set
        """
        for i, pattern in enumerate(url_patterns):
            self.add_rule(InterceptRule(
                name=f"{name or 'block'}-{i}",
                url_pattern=pattern,
                action="block",
            ))

    def add_redirect(self, from_pattern: str, to_url: str, name: str = "redirect") -> None:
        """Redirect requests matching a URL pattern to a different URL.

        Args:
            from_pattern: Substring to match in request URLs
            to_url: URL to redirect to
            name: Rule name
        """
        self.add_rule(InterceptRule(
            name=name,
            url_pattern=from_pattern,
            action="redirect",
            redirect_url=to_url,
        ))

    def mock_endpoint(self, url_pattern: str, body: str, status: int = 200,
                      content_type: str = "application/json", name: str = "mock") -> None:
        """Mock responses for requests matching a URL pattern.

        Args:
            url_pattern: Substring to match in request URLs
            body: Response body string
            status: HTTP status code (default: 200)
            content_type: Content-Type header (default: application/json)
            name: Rule name
        """
        self.add_rule(InterceptRule(
            name=name,
            url_pattern=url_pattern,
            action="mock",
            mock_status=status,
            mock_body=body,
            mock_content_type=content_type,
        ))


# ---------------------------------------------------------------------------
# Cookie and session management
# ---------------------------------------------------------------------------

class CDPCookieManager:
    """Comprehensive cookie and session manager using CDP Network domain.

    Provides high-level cookie operations beyond the basic CDPBrowser methods:
      - Bulk import/export of cookies (for session persistence)
      - Cookie profiles (save/restore sets of cookies)
      - Session state management (login sessions, auth tokens)
      - Cookie filtering and search
      - Automatic session health checking

    Usage:
        async with CDPBrowser() as browser:
            mgr = CDPCookieManager(browser)
            await mgr.start()

            # Export current cookies
            cookies = await mgr.export_cookies()

            # Import cookies (e.g., from a saved session)
            await mgr.import_cookies(cookies)

            # Save a session profile
            await mgr.save_profile("logged-in")

            # Restore a session profile
            await mgr.restore_profile("logged-in")

            # Check session health
            healthy = await mgr.check_session("example.com")

            await mgr.stop()
    """

    def __init__(self, browser: CDPBrowser):
        self._browser = browser
        self._profiles: Dict[str, List[Dict]] = {}
        self._active = False

    # -- Lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Enable cookie management (ensures Network domain is enabled)."""
        if self._active:
            return
        # Network.enable is idempotent if already enabled
        await self._browser.send("Network.enable")
        self._active = True
        logger.info("[CDPCookieManager] Started")

    async def stop(self) -> None:
        """Stop cookie management (does NOT disable Network domain)."""
        # Don't disable Network — other consumers may need it
        self._active = False
        logger.info("[CDPCookieManager] Stopped")

    @property
    def active(self) -> bool:
        """Whether cookie management is active."""
        return self._active

    # -- Basic operations ----------------------------------------------------

    async def get_all_cookies(self) -> List[Dict]:
        """Get ALL cookies from the browser (across all domains).

        Returns:
            List of cookie dicts with name, value, domain, path, etc.

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        res = await self._browser.send("Network.getAllCookies")
        if res and "result" in res:
            return res["result"].get("cookies", [])
        return []

    async def get_cookies_for_url(self, url: str) -> List[Dict]:
        """Get cookies that would be sent with a request to the given URL.

        Args:
            url: The URL to match cookies against

        Returns:
            List of matching cookie dicts

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        res = await self._browser.send("Network.getCookies", {"urls": [url]})
        if res and "result" in res:
            return res["result"].get("cookies", [])
        return []

    def _ensure_active(self) -> None:
        """Raise RuntimeError if cookie manager is not started."""
        if not self._active:
            raise RuntimeError("CDPCookieManager is not started. Call await mgr.start() first.")

    async def set_cookie(self, name: str, value: str, domain: str = "",
                         path: str = "/", secure: bool = False,
                         http_only: bool = False, same_site: str = "",
                         expires: Optional[float] = None,
                         priority: str = "Medium",
                         same_party: bool = False,
                         source_scheme: str = "NonSecure") -> bool:
        """Set a cookie with full options.

        Args:
            name: Cookie name (must not be empty)
            value: Cookie value
            domain: Cookie domain (e.g., ".example.com")
            path: Cookie path (default: "/")
            secure: Whether the cookie requires HTTPS
            http_only: Whether the cookie is HTTP-only (no JS access)
            same_site: SameSite policy ("Strict", "Lax", "None", or "")
            expires: Expiration as UTC timestamp (None = session cookie)
            priority: Cookie priority ("Low", "Medium", "High")
            same_party: SameParty attribute
            source_scheme: "Secure" or "NonSecure"

        Returns:
            True if the cookie was set successfully

        Raises:
            ValueError: if name is empty or same_site is invalid
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        if not name:
            raise ValueError("Cookie name must not be empty")
        if same_site and same_site not in ("Strict", "Lax", "None"):
            raise ValueError(f"Invalid sameSite value: {same_site!r}. Must be Strict, Lax, None, or empty.")
        params = {
            "name": name,
            "value": value,
            "path": path,
            "secure": secure,
            "httpOnly": http_only,
            "priority": priority,
            "sameParty": same_party,
            "sourceScheme": source_scheme,
        }
        if domain:
            params["domain"] = domain
        if same_site:
            params["sameSite"] = same_site
        if expires is not None:
            params["expires"] = expires

        res = await self._browser.send("Network.setCookie", params)
        return res and res.get("result", {}).get("success", False)

    async def delete_cookie(self, name: str, domain: str = "",
                            path: str = "/") -> None:
        """Delete a cookie by name, optionally filtered by domain and path.

        Args:
            name: Cookie name to delete
            domain: If specified, only delete cookies matching this domain
            path: If specified, only delete cookies matching this path

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        params = {"name": name}
        if domain:
            params["domain"] = domain
        if path:
            params["path"] = path
        await self._browser.send("Network.deleteCookies", params)

    async def clear_cookies(self) -> None:
        """Clear ALL cookies from the browser.

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        await self._browser.send("Network.clearBrowserCookies")

    # -- Bulk operations -----------------------------------------------------

    async def export_cookies(self, domain_filter: Optional[str] = None) -> List[Dict]:
        """Export cookies, optionally filtered by domain.

        Args:
            domain_filter: If specified, only export cookies whose domain
                          contains this substring

        Returns:
            List of cookie dicts suitable for import_cookies()
        """
        cookies = await self.get_all_cookies()
        if domain_filter:
            cookies = [c for c in cookies if domain_filter in c.get("domain", "")]
        return cookies

    async def import_cookies(self, cookies: List[Dict]) -> int:
        """Import a list of cookies into the browser.

        Uses concurrent import for speed with semaphore-limited parallelism.

        Args:
            cookies: List of cookie dicts (as returned by export_cookies)

        Returns:
            Number of cookies successfully imported

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        if not cookies:
            return 0

        sem = asyncio.Semaphore(10)  # Max 10 concurrent cookie sets

        async def _import_one(cookie: Dict) -> bool:
            async with sem:
                return await self.set_cookie(
                    name=cookie.get("name", ""),
                    value=cookie.get("value", ""),
                    domain=cookie.get("domain", ""),
                    path=cookie.get("path", "/"),
                    secure=cookie.get("secure", False),
                    http_only=cookie.get("httpOnly", False),
                    same_site=cookie.get("sameSite", ""),
                    expires=cookie.get("expires"),
                    priority=cookie.get("priority", "Medium"),
                )

        results = await asyncio.gather(*[_import_one(c) for c in cookies], return_exceptions=True)
        count = sum(1 for r in results if r is True)
        logger.info("[CDPCookieManager] Imported %d/%d cookies", count, len(cookies))
        return count

    # -- Profile management --------------------------------------------------

    async def save_profile(self, name: str, domain_filter: Optional[str] = None) -> int:
        """Save current cookies as a named profile.

        Args:
            name: Profile name
            domain_filter: If specified, only save cookies matching this domain

        Returns:
            Number of cookies saved in the profile
        """
        cookies = await self.export_cookies(domain_filter)
        self._profiles[name] = cookies
        logger.info("[CDPCookieManager] Profile '%s' saved with %d cookies", name, len(cookies))
        return len(cookies)

    async def restore_profile(self, name: str, clear_first: bool = True) -> int:
        """Restore a saved cookie profile.

        If clear_first is True, imports cookies FIRST, then clears and re-imports
        to ensure atomicity (rollback on failure).

        Args:
            name: Profile name
            clear_first: If True, clear all existing cookies before restoring

        Returns:
            Number of cookies successfully restored

        Raises:
            KeyError: if the profile name doesn't exist
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        if name not in self._profiles:
            raise KeyError(f"Cookie profile '{name}' not found. Available: {list(self._profiles.keys())}")

        cookies = self._profiles[name]

        if clear_first:
            # Save current state for rollback
            current_cookies = await self.export_cookies()
            await self.clear_cookies()
            count = await self.import_cookies(cookies)
            if count == 0 and len(cookies) > 0:
                # Rollback: restore previous cookies
                logger.warning("[CDPCookieManager] Profile restore failed, rolling back")
                await self.import_cookies(current_cookies)
                return 0
        else:
            count = await self.import_cookies(cookies)

        logger.info("[CDPCookieManager] Profile '%s' restored: %d/%d cookies", name, count, len(cookies))
        return count

    def list_profiles(self) -> List[str]:
        """List all saved profile names."""
        return list(self._profiles.keys())

    def delete_profile(self, name: str) -> bool:
        """Delete a saved profile. Returns True if found and deleted."""
        if name in self._profiles:
            del self._profiles[name]
            return True
        return False

    def get_profile_info(self, name: str) -> Optional[Dict]:
        """Get info about a saved profile without restoring it."""
        if name not in self._profiles:
            return None
        cookies = self._profiles[name]
        domains = set(c.get("domain", "") for c in cookies)
        return {
            "name": name,
            "cookie_count": len(cookies),
            "domains": sorted(domains),
        }

    # -- Session health check ------------------------------------------------

    async def check_session(self, domain: str, auth_cookie_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """Check the health of a login session for a domain.

        Examines cookies for the given domain and reports on session health:
          - Whether auth-related cookies exist
          - Whether any cookies are expired or about to expire
          - Session cookie count and domains

        Args:
            domain: Domain to check (e.g., "example.com")
            auth_cookie_names: List of cookie names that indicate authentication.
                             If None, looks for common patterns: session, token, auth, sid.

        Returns:
            Dict with session health information
        """
        cookies = await self.get_cookies_for_url(f"https://{domain}")
        # Also check HTTP scheme for non-secure cookies
        if not cookies:
            cookies_http = await self.get_cookies_for_url(f"http://{domain}")
            cookies = cookies_http or cookies
        now = time.time()

        if auth_cookie_names is None:
            auth_cookie_names = ["session", "token", "auth", "sid", "sessionid",
                                "session_id", "access_token", "refresh_token",
                                "jwt", "csrf"]

        auth_cookies = []
        expiring_soon = []
        expired = []

        for c in cookies:
            name_lower = c.get("name", "").lower()
            # Check if this is an auth cookie
            is_auth = any(pattern in name_lower for pattern in auth_cookie_names)
            if is_auth:
                auth_cookies.append(c)

            # Check expiration
            expires = c.get("expires", -1)
            if expires > 0:
                if expires < now:
                    expired.append(c)
                elif expires < now + 3600:  # Within 1 hour
                    expiring_soon.append(c)

        has_auth = len(auth_cookies) > 0
        all_cookies_count = len(cookies)

        return {
            "domain": domain,
            "healthy": has_auth and len(expired) == 0,
            "has_auth_cookies": has_auth,
            "auth_cookies": [c.get("name") for c in auth_cookies],
            "total_cookies": all_cookies_count,
            "expired_count": len(expired),
            "expiring_soon_count": len(expiring_soon),
            "expired": [c.get("name") for c in expired],
            "expiring_soon": [c.get("name") for c in expiring_soon],
        }
