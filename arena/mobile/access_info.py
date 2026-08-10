"""How to reach this bridge, answered honestly.

The Android app can show a status screen, but a status screen is useless
if the only reachable address is loopback inside the phone. Ivan's
actual goal is to hand out a URL and a token that work from somewhere
else -- and after a reboot the phone dropped off wireless ADB entirely
(Android turns it back off), so nothing could be repaired from outside.
Whatever the app shows has to be enough on its own.

Three separate questions, deliberately not merged:

  * **Where is the bridge listening?** A loopback bind means no
    remote access is possible at all, no matter what tunnels exist.
  * **What addresses does this device have?** A LAN address only helps
    on the same network, and it changes.
  * **Is a tunnel up?** That is the only answer that survives leaving
    the house.

Each is reported with what it is, never blended into one optimistic
"you're online". This module states what is true and lets the caller
decide -- the same rule the release and probe gates were written under.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any

# This set exists precisely to recognise a loopback bind; naming the
# addresses is the feature, not debug code left behind.
LOOPBACK_BINDS = frozenset({"127.0.0.1", "localhost", "::1", ""})  # DevSkim: ignore DS162092


def _is_loopback(addr: str) -> bool:
    if addr in LOOPBACK_BINDS:
        return True
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def local_addresses() -> list[dict[str, str]]:
    """Every non-loopback IPv4 address configured on this device.

    ``socket.getaddrinfo`` on the hostname is used rather than parsing
    ``ip addr``: it needs no external binary, which matters because the
    app cannot run Termux's tools and Android's own toolbox is minimal.
    """
    seen: dict[str, dict[str, str]] = {}
    try:
        host = socket.gethostname()
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        # sockaddr is a 2-tuple for IPv4 and a 4-tuple for IPv6; only the
        # first element is the address in both, but the static type is a
        # union, so narrow it explicitly rather than indexing blind.
        sockaddr = info[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            continue
        addr = str(sockaddr[0])
        if _is_loopback(addr):
            continue
        seen[addr] = {"address": addr, "kind": _classify(addr)}

    # getaddrinfo misses interfaces the hostname does not resolve to,
    # which on a phone is most of them. A UDP socket to a routable
    # address reveals the source IP without sending a packet.
    # 100.100.100.100 is Tailscale's MagicDNS resolver, always inside the
    # tailnet. Probing it reveals the tun0 source address, which the
    # public-internet probes below never see: the default route goes out
    # wlan0, so they only ever report the LAN IP.
    #
    # Found by using it. The phone was answering this very request over
    # its tailnet address while `addresses` listed only 192.168.50.181 --
    # the endpoint omitting the interface that was carrying it. Same
    # shape as v4.169.16, where /v1/access denied being reachable through
    # the tunnel it was replying over.
    for probe in ("100.100.100.100", "8.8.8.8", "1.1.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect((probe, 53))
                addr = s.getsockname()[0]
            finally:
                s.close()
        except OSError:
            continue
        if addr and not _is_loopback(addr):
            seen.setdefault(addr, {"address": addr, "kind": _classify(addr)})
    return sorted(seen.values(), key=lambda d: d["address"])


def _classify(addr: str) -> str:
    """Name the range, because they are reachable from different places."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return "unknown"
    if ip in ipaddress.ip_network("100.64.0.0/10"):
        # Tailscale hands these out; reachable from anywhere on the tailnet.
        return "tailnet"
    if ip.is_private:
        return "lan"
    return "public"


def describe(*, bind: str, port: int, tunnels: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the phone app needs to render a working address.

    ``reachable_remotely`` follows the tunnels, not the bind -- and that
    correction came from catching myself lying.

    The first version declared that a loopback bind meant unreachable
    "not even through a tunnel". It was written, shipped, and then used
    to inspect the PC bridge *over ngrok*, which reported
    a loopback bind while answering the very request that proved it
    wrong. A tunnel client runs on the same host: it connects to
    loopback locally and forwards from outside. Loopback blocks direct
    LAN access; it does not block a local tunnel agent.

    So the two are reported as what they are: ``reachable_on_lan``
    depends on the bind, ``reachable_remotely`` depends on a tunnel
    being up. Conflating them produced a confident sentence that the
    response body itself refuted.
    """
    loopback = _is_loopback(bind)
    addrs = [] if loopback else local_addresses()
    # Plain http, deliberately: the bridge has no TLS listener, so this
    # is the scheme that actually works. What was missing is saying so.
    # devskim flagged the literal (DS137138 InsecureUrl) and it was
    # right about the fact, if not about the fix -- these URLs carry the
    # bearer token, and on a LAN or a shared tailnet that is readable by
    # anything on the path. A reader who sees a URL and no warning
    # reasonably assumes someone checked.
    urls = [f"http://{a['address']}:{port}" for a in addrs]  # DevSkim: ignore DS137138

    tunnel_urls: list[str] = []
    for name, snap in (tunnels or {}).items():
        if not isinstance(snap, dict):
            continue
        url = snap.get("public_url")
        if url and snap.get("active"):
            tunnel_urls.append(str(url))
        elif url and snap.get("connected"):
            tunnel_urls.append(str(url))
        del name

    info: dict[str, Any] = {
        "ok": True,
        "bind": bind,
        "port": port,
        "loopback_only": loopback,
        "addresses": addrs,
        "lan_urls": urls,
        "lan_urls_are_plaintext": bool(urls),
        "tunnel_urls": tunnel_urls,
        # A tunnel agent runs locally and dials 127.0.0.1, so it works
        # regardless of the bind. Only direct LAN access needs the wider
        # bind.
        "reachable_remotely": bool(tunnel_urls),
        "reachable_on_lan": bool(urls),
    }
    if loopback and tunnel_urls:
        info["why"] = (
            f"bound to {bind or '127.0.0.1'}: no direct connections from other "  # DevSkim: ignore DS162092
            f"machines, but the tunnel forwards from outside because its agent "
            f"runs on this device and dials loopback itself."
        )
    elif loopback:
        info["why"] = (
            f"the bridge is bound to {bind or '127.0.0.1'}, so no other machine "  # DevSkim: ignore DS162092
            f"can connect directly. Either start a tunnel -- its agent runs here "
            f"and can reach loopback -- or restart with --bind 0.0.0.0 for LAN "
            f"access."
        )
    elif not urls and not tunnel_urls:
        info["why"] = "bound for remote access, but this device has no usable address yet"
    if urls:
        # Separate key rather than folded into `why`: the tunnels carry
        # TLS and these do not, and a caller choosing between them
        # should not have to parse prose to find that out.
        info["transport_warning"] = (
            "lan_urls are plain HTTP -- the bridge has no TLS listener, so "
            "the bearer token travels in clear text to anything on the "
            "network path. Prefer a tunnel URL off-device; keep LAN access "
            "to networks you trust."
        )
    return info


__all__ = ["describe", "local_addresses"]
