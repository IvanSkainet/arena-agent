"""Extracted module from scripts/cdp_browser.py."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403

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

    # HOME — critical for Chromium to find its config/cache dirs
    if not env.get("HOME"):
        import pwd
        try:
            env["HOME"] = pwd.getpwuid(uid).pw_dir
        except Exception:
            env["HOME"] = f"/home/{uid}"

    # XDG_RUNTIME_DIR — needed by many Linux components
    if not env.get("XDG_RUNTIME_DIR"):
        xdg = f"/run/user/{uid}"
        if os.path.isdir(xdg):
            env["XDG_RUNTIME_DIR"] = xdg
        else:
            # Create it if it doesn't exist (some minimal environments)
            try:
                os.makedirs(xdg, mode=0o700, exist_ok=True)
                env["XDG_RUNTIME_DIR"] = xdg
            except Exception:
                pass

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

    # LD_LIBRARY_PATH — include Chromium's lib directory for resource loading
    chromium_lib_dirs = ["/usr/lib/chromium", "/usr/lib64/chromium", "/usr/lib/chromium-browser"]
    existing_lib_dirs = [d for d in chromium_lib_dirs if os.path.isdir(d)]
    if existing_lib_dirs:
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        for d in existing_lib_dirs:
            if d not in existing_ld:
                existing_ld = f"{d}:{existing_ld}" if existing_ld else d
        env["LD_LIBRARY_PATH"] = existing_ld

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
    - --remote-debugging-address=127.0.0.1: Explicitly bind to localhost.
    - --disable-features=VizDisplayCompositor: Needed for some headless configs.
    """
    cmd = [
        exe,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
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
        "--disable-features=VizDisplayCompositor",
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
