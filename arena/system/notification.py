"""Cross-platform visual notification helpers (v4.91.0)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any


def notify_windows(title: str, message: str) -> bool:
    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
$template = '<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{message}</text></binding></visual></toast>'
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Arena Unified Bridge").Show($toast)
"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script], 
                       capture_output=True, timeout=5, check=True)
        return True
    except Exception:
        return False


def notify_linux(title: str, message: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.run(["notify-send", title, message], timeout=5, check=True)
        return True
    except Exception:
        return False


def notify_macos(title: str, message: str) -> bool:
    if not shutil.which("osascript"):
        return False
    script = f'display notification "{message}" with title "{title}"'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, check=True)
        return True
    except Exception:
        return False


def send_notification(title: str, message: str) -> dict[str, Any]:
    title = (title or "Arena Bridge").replace('"', "'")
    message = (message or "").replace('"', "'")
    ok = False
    method = "unknown"
    if sys.platform == "win32":
        ok = notify_windows(title, message)
        method = "powershell_toast"
    elif sys.platform == "darwin":
        ok = notify_macos(title, message)
        method = "osascript"
    else:
        ok = notify_linux(title, message)
        method = "notify-send"
    return {"ok": ok, "method": method, "title": title, "message": message}
