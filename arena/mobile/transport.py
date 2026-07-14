"""Transport management endpoints (v3.84.5).

Sits above `arena.mobile.adb_fallback`'s registry and turns it into
something the HTTP layer can drive:

* `enable_tcp(serial)` -- one-shot: put a USB-connected phone into
  TCP/IP mode (`adb tcpip 5555`), probe its wlan0 address, `adb
  connect ip:5555`, register the resulting alias in the fallback
  registry. Safe to call more than once -- if a wireless transport
  already exists we just re-verify it.

* `disable_tcp(serial)` -- kill the TCP transport and forget the
  alias.

* `describe(serial)` -- return the registry snapshot plus a couple of
  derived fields (is_multi_transport, active_transport) so a UI can
  render it without duplicating the logic.

Everything here goes through `arena.mobile.adb.run` -- the same
subprocess wrapper the rest of the mobile stack uses -- so
platform-specific behaviour (Windows CREATE_NO_WINDOW, ADB_PATH
override, etc.) is inherited for free.
"""
from __future__ import annotations

import re
from typing import Any

from arena.mobile import adb_fallback as _fb
from arena.mobile.adb import AdbNotFoundError, find_adb, run


DEFAULT_TCP_PORT = 5555

# Matches an IPv4-only host:port so we can reject junk before it lands
# in an adb command line. IPv6-ADB is not supported by upstream today.
_HOSTPORT_RE = re.compile(r"^(?P<host>(?:\d{1,3}\.){3}\d{1,3}):(?P<port>\d{1,5})$")

# Loose match for "192.168.1.5" inside `ip -4 addr show wlan0` output.
_INET_RE = re.compile(r"inet\s+((?:\d{1,3}\.){3}\d{1,3})/")


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def _probe_wifi_ip(serial: str) -> str | None:
    """Return the phone's wlan0 IPv4 address, or None. Tries several
    common interface names because vendors rename wlan0 to `wlan1` or
    `wlan-mlo0` on newer chipsets. Uses `no_route=True` so we hit the
    USB transport directly -- routing to an already-known wireless
    alias would defeat the point (we're trying to *discover* the alias)."""
    for iface in ("wlan0", "wlan1", "wlan-mlo0"):
        try:
            r = run(["shell", "ip", "-4", "addr", "show", iface],
                    serial=serial, timeout=6, no_route=True)
        except Exception:
            continue
        if r.returncode != 0:
            continue
        text = (r.stdout or "") + " " + (r.stderr or "")
        m = _INET_RE.search(text)
        if m:
            return m.group(1)
    return None


def _try_connect(host: str, port: int, *, timeout: int = 8) -> tuple[bool, str]:
    """Run `adb connect host:port` and interpret the outcome."""
    try:
        r = run(["connect", f"{host}:{port}"], timeout=timeout)
    except AdbNotFoundError as e:
        return False, str(e)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    ok = ("connected" in out.lower()) and ("failed" not in out.lower())
    return ok, out


def enable_tcp(serial: str, *,
               port: int = DEFAULT_TCP_PORT,
               host: str | None = None) -> dict[str, Any]:
    """Put the USB-connected phone into TCP/IP mode and register the
    wireless address as a fallback transport.

    Behaviour:
      1. If `host` is provided we skip IP probing entirely (caller
         already knows the address, e.g. from a QR code).
      2. Otherwise, run `adb -s <serial> tcpip <port>` first (this
         restarts adbd on the phone in TCP mode). Wait briefly, then
         probe wlan0 for an IPv4.
      3. `adb connect host:port`. On success, register `host:port` as
         an alias for `serial` in the transport registry.
    """
    guard = _ensure_adb()
    if guard:
        return guard
    if not isinstance(serial, str) or not serial.strip():
        return _err("serial must be a non-empty string")
    if not (0 < int(port) < 65536):
        return _err(f"invalid port {port}")

    stages: list[dict[str, Any]] = []

    if host is None:
        # Step 1: probe the phone's wlan IPv4 while USB is still up.
        # (After `adb tcpip` restarts adbd on the phone, the USB serial
        # may briefly disappear -- probing first avoids that race.)
        host = _probe_wifi_ip(serial)
        stages.append({"stage": "probe_ip", "wifi_ip": host})
        if not host:
            return _err(
                "could not determine phone's wifi IP",
                hint="Verify the phone is on Wi-Fi and try again.",
                stages=stages,
            )

        # Step 2: restart adbd in tcp mode. Needs USB, so opt out of
        # the transport routing (no_route=True) -- we specifically need
        # to hit the USB transport by name.
        try:
            r = run(["tcpip", str(port)], serial=serial,
                    timeout=8, no_route=True)
        except AdbNotFoundError as e:
            return _err(str(e))
        stages.append({
            "stage": "tcpip",
            "returncode": r.returncode,
            "stdout": (r.stdout or "").strip(),
            "stderr": (r.stderr or "").strip(),
        })
        if r.returncode != 0:
            return _err(
                "adb tcpip failed -- is the device connected via USB?",
                stages=stages,
            )
        # `adb tcpip` returns immediately; adbd needs ~1s to re-bind
        # before `adb connect` will succeed.
        import time
        time.sleep(1.5)

    # Step 3: adb connect.
    ok, connect_out = _try_connect(host, int(port))
    stages.append({
        "stage": "connect",
        "ok": ok,
        "host": host, "port": int(port),
        "output": connect_out,
    })
    if not ok:
        return _err(
            f"adb connect {host}:{port} failed",
            output=connect_out,
            stages=stages,
        )

    alias = f"{host}:{int(port)}"
    _fb.add_alias(serial, alias, kind="tcp")
    stages.append({"stage": "register", "alias": alias})
    return {
        "ok": True,
        "action": "transport.enable_tcp",
        "serial": serial,
        "alias": alias,
        "stages": stages,
        "registry": _fb.snapshot(serial),
    }


def disable_tcp(serial: str, *, alias: str | None = None) -> dict[str, Any]:
    """Drop every TCP alias for `serial` (or just one specific alias)
    and best-effort `adb disconnect` it."""
    guard = _ensure_adb()
    if guard:
        return guard
    snap = _fb.snapshot(serial)
    if not snap:
        return _err(f"no transport record for {serial!r}")
    dropped: list[str] = []
    for tr in snap[0].get("transports", []):
        addr = tr.get("address")
        if not addr or tr.get("kind") != "tcp":
            continue
        if alias and addr != alias:
            continue
        if _fb.drop_alias(serial, addr):
            dropped.append(addr)
            try:
                run(["disconnect", addr], timeout=5)
            except Exception:
                pass
    return {
        "ok": True,
        "action": "transport.disable_tcp",
        "serial": serial,
        "dropped": dropped,
        "registry": _fb.snapshot(serial),
    }


def describe(serial: str | None = None) -> dict[str, Any]:
    """Return the fallback registry snapshot plus a couple of derived
    fields the dashboard cares about."""
    snap = _fb.snapshot(serial)
    for dev in snap:
        transports = dev.get("transports", [])
        healthy_addrs = [t["address"] for t in transports if t.get("healthy")]
        dev["is_multi_transport"] = len(transports) > 1
        dev["active_transport"] = healthy_addrs[0] if healthy_addrs else (
            transports[0]["address"] if transports else None
        )
    return {"ok": True, "devices": snap}


def parse_hostport(s: str) -> tuple[str, int] | None:
    """Strict host:port validator for HTTP handlers."""
    m = _HOSTPORT_RE.match((s or "").strip())
    if not m:
        return None
    port = int(m.group("port"))
    if not (0 < port < 65536):
        return None
    return m.group("host"), port
