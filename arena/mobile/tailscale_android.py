"""Tailscale detection on Android, where there is no CLI to shell out to.

`arena/admin/tailscale.py` answers "is Tailscale here?" by running the
`tailscale` binary. On a desktop that is correct. On Android it is
structurally wrong: Tailscale ships as an ordinary app
(`com.tailscale.ipn`) with no command-line entry point at all, so the
binary lookup fails, `sys_funnel_status` reports
`"tailscale not found"`, and the transport list shows Tailscale as
absent on a phone where the VPN is connected and working.

Verified on the POCO F7 Pro (Android 16): `com.tailscale.ipn` installed,
`ip addr show tailscale0` reports the interface does not exist -- Android
routes the tunnel through a VpnService rather than a named interface, so
even the interface check is not a reliable signal from inside Termux.

What *is* reliable, in descending order of confidence:

  1. the package being installed (`pm list packages`), and
  2. an interface or route carrying a 100.64.0.0/10 address, which is
     the CGNAT range Tailscale hands out.

Neither proves the tunnel is up on its own, so both are reported
separately and the caller is told which signal fired. Guessing "probably
connected" from a package listing would be the same failure this project
keeps hitting: a check that cannot tell "yes" from "I could not look".
"""
from __future__ import annotations

import ipaddress
import shutil
import subprocess  # nosec B404 -- fixed argv, no shell, Android-local probes
from typing import Any

PACKAGE = "com.tailscale.ipn"
# Tailscale assigns from the CGNAT block; RFC 6598 reserves it, so an
# address in this range on a phone means a tailnet in practice.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _run(argv: list[str], timeout: int = 6) -> str:
    try:
        out = subprocess.run(  # nosec B603 -- fixed argv, shell=False
            argv, capture_output=True, text=True, timeout=timeout, check=False,
        )
        return (out.stdout or "") + (out.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def package_installed() -> bool:
    """True when the Tailscale app is installed on this device."""
    if not shutil.which("pm"):
        return False
    return PACKAGE in _run(["pm", "list", "packages", PACKAGE])


def cgnat_addresses() -> list[str]:
    """Any 100.64.0.0/10 address currently configured on this device."""
    found: list[str] = []
    if not shutil.which("ip"):
        return found
    for raw in _run(["ip", "-4", "addr"]).splitlines():
        # `ip addr` indents the inet lines under each interface, so a
        # startswith() on the unstripped line silently matches nothing --
        # which reads exactly like "no tailnet here".
        parts = raw.split()
        if len(parts) < 2 or "inet" not in parts:
            continue
        candidate = parts[parts.index("inet") + 1].split("/")[0]
        try:
            if ipaddress.ip_address(candidate) in _CGNAT:
                found.append(candidate)
        except ValueError:
            continue
    return found


def status() -> dict[str, Any]:
    """Android-native Tailscale status.

    ``installed`` is a fact. ``connected`` is only claimed when an actual
    tailnet address is present; a bare package listing is reported as
    ``installed`` with ``connected: False`` and an explicit reason, never
    as an optimistic guess.
    """
    installed = package_installed()
    addrs = cgnat_addresses()
    info: dict[str, Any] = {
        "provider": "tailscale",
        "platform": "android",
        "installed": installed,
        "connected": bool(addrs),
        "addresses": addrs,
        "manageable": False,
        "cli": False,
    }
    if not installed:
        info["reason"] = (
            f"the {PACKAGE} app is not installed; on Android Tailscale has no "
            f"CLI, so the desktop binary lookup can never find it"
        )
    elif not addrs:
        info["reason"] = (
            "the app is installed but no 100.64.0.0/10 address is configured; "
            "the VPN is most likely switched off. Android routes the tunnel "
            "through VpnService, so there is no tailscale0 interface to check "
            "and no CLI to ask -- this cannot be determined more precisely "
            "from inside Termux."
        )
    else:
        info["reason"] = "tailnet address present"
    return info


__all__ = ["PACKAGE", "cgnat_addresses", "package_installed", "status"]
