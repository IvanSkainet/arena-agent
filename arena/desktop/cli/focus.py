"""Desktop manager focus/window-manager helpers."""
from __future__ import annotations

from arena.desktop.cli.common import *  # noqa: F401,F403

def _detect_wm():
    """Detect if a window manager is currently running."""
    # Check EWMH compatibility hint — set by any EWMH-compliant WM
    if have('xdotool'):
        p = run('xdotool getwindowfocus 2>/dev/null', timeout=3)
        if p.returncode == 0 and p.stdout.strip():
            return 'ewmh_active'
    # Check for running WM processes
    for wm in ['openbox', 'fluxbox', 'i3', 'mutter', 'kwin_wayland', 'kwin_x11', 'gnome-shell', 'xfwm4']:
        p = run(f'pgrep -x {wm}', timeout=3)
        if p.returncode == 0:
            return wm
    return None

def _ensure_wm():
    """Auto-start a lightweight window manager if none is running.
    
    Without a WM, keyboard events from xdotool/ydotool don't reach
    application windows because no window has EWMH focus.
    """
    global _wm_started
    if _wm_started:
        return True
    
    wm = _detect_wm()
    if wm:
        _wm_started = True
        return True
    
    display = os.environ.get('DISPLAY', '')
    if not display:
        return False  # No display at all — can't start WM
    
    # Try openbox first (lightweight, most common in containers)
    for wm_cmd, wm_name in [
        ('openbox', 'openbox'),
        ('fluxbox', 'fluxbox'),
        ('i3', 'i3'),
        ('mutter', 'mutter'),
    ]:
        if have(wm_cmd):
            # Start WM in background — replace any existing WM
            subprocess.Popen(
                f'DISPLAY={shq(display)} {wm_cmd} &>/dev/null &',
                shell=True
            )
            time.sleep(1.5)  # Give WM time to start
            # Verify it started
            verify = _detect_wm()
            if verify:
                _wm_started = True
                return True
    
    return False

def _focus_window_at(x, y):
    """Focus the window at screen coordinates (x, y) using xdotool.
    
    This is critical for key events to reach the right application.
    On X11 without EWMH, xdotool key events go to the focused window,
    so we must focus the target window before sending keys.
    """
    if not have('xdotool'):
        return False
    
    # Method 1: Click-to-focus (most reliable on any WM)
    # Move mouse to position and click (left button) to activate window
    run(f'xdotool mousemove --sync {x} {y}', timeout=3)
    time.sleep(0.05)
    run(f'xdotool click 1', timeout=3)
    time.sleep(0.1)
    return True

def _focus_active_window():
    """Focus the currently active window using xdotool.
    
    This re-activates the focused window, which helps on some WMs
    where focus was lost.
    """
    if not have('xdotool'):
        return False
    p = run('xdotool getactivewindow 2>/dev/null', timeout=3)
    if p.returncode == 0 and p.stdout.strip():
        wid = p.stdout.strip().splitlines()[0]
        run(f'xdotool windowfocus {wid}', timeout=3)
        run(f'xdotool windowactivate {wid}', timeout=3)
        return True
    return False
