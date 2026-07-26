"""Cross-platform visual notification helpers.

v4.91.0 introduced these; v4.93.0 fixes a false-positive on Windows: the
toast was created with an unregistered AppUserModelID ("Arena Unified
Bridge"), which Windows silently drops while PowerShell still exits 0 -- so
``ok`` reported ``true`` even though nothing appeared on screen. The toast
now uses PowerShell's own *registered* AUMID (so it actually renders in the
notification area), runs with ``$ErrorActionPreference=Stop`` + try/catch so
a genuine failure surfaces as a non-zero exit (-> ``ok: false`` with a
``detail``), and escapes title/message for both the XML payload and the
PowerShell single-quoted string. Each notifier returns ``(ok, detail)``.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any

# PowerShell's registered AppUserModelID. A desktop process can only show a
# toast under an AUMID that Windows knows about; an arbitrary string is
# dropped without error. PowerShell's AUMID is always registered, so the
# toast renders reliably (the toast *title* still says "Arena Bridge"; only
# the system "app name" line shows Windows PowerShell).
_POWERSHELL_AUMID = (
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
    "\\WindowsPowerShell\\v1.0\\powershell.exe"
)


def _xml_escape(s: str) -> str:
    """Escape a string for use inside XML text content."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def notify_windows(title: str, message: str) -> tuple[bool, str]:
    def esc(s: str) -> str:
        # XML text-content escape, then double single quotes so an apostrophe
        # cannot terminate the PowerShell single-quoted string wrapping the XML.
        return _xml_escape(s).replace("'", "''")

    t = esc(title)
    m = esc(message)
    xml = (
        '<toast><visual><binding template="ToastGeneric">'
        "<text>" + t + "</text><text>" + m + "</text>"
        "</binding></visual></toast>"
    )
    ps = (
        "$ErrorActionPreference='Stop';"
        "try{"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
        "$x=[Windows.Data.Xml.Dom.XmlDocument]::new();"
        "$x.LoadXml('" + xml + "');"
        "$t=[Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('"
        + _POWERSHELL_AUMID + "').Show($t)"
        "}catch{Write-Error $_.Exception.Message;exit 1}"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=8, check=True, text=True,
        )
        return True, ""
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()[:300]
        return False, detail or f"powershell exit {e.returncode}"
    except Exception as e:  # noqa: BLE001 - report any failure honestly
        return False, str(e)[:300]


def notify_macos(title: str, message: str) -> tuple[bool, str]:
    if not shutil.which("osascript"):
        return False, "osascript not found"

    def esc(s: str) -> str:
        # Escape for an AppleScript double-quoted string literal.
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    try:
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, timeout=5, check=True, text=True)
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or "").strip()[:300] or f"osascript exit {e.returncode}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


def notify_linux(title: str, message: str) -> tuple[bool, str]:
    if not shutil.which("notify-send"):
        return False, "notify-send not found"
    try:
        # argv form (no shell) -- title/message need no escaping.
        subprocess.run(["notify-send", title, message],
                       capture_output=True, timeout=5, check=True, text=True)
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or "").strip()[:300] or f"notify-send exit {e.returncode}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


def send_notification(title: str, message: str) -> dict[str, Any]:
    title = title or "Arena Bridge"
    message = message or ""
    if sys.platform == "win32":
        ok, detail = notify_windows(title, message)
        method = "powershell_toast"
    elif sys.platform == "darwin":
        ok, detail = notify_macos(title, message)
        method = "osascript"
    else:
        ok, detail = notify_linux(title, message)
        method = "notify-send"
    result: dict[str, Any] = {
        "ok": ok, "method": method, "title": title, "message": message,
    }
    if not ok:
        result["detail"] = (
            detail
            or "notification could not be displayed (the bridge may be running "
               "in a non-interactive session, or OS notifications are disabled)"
        )
    return result
