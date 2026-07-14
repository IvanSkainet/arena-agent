"""Wireless ADB pair + connect.

Android 11+ lets a phone accept ADB commands over Wi-Fi after a one-time
pairing handshake. The flow from the Dashboard's perspective:

  1. On the phone: Settings → Developer options → Wireless debugging →
     "Pair device with pairing code". The phone shows a 6-digit code
     and a host:port pair (usually ephemeral, e.g. 192.168.1.5:38571).
  2. User pastes host:port + code into the Dashboard.
  3. POST /v1/mobile/pair {host, port, code} → we run `adb pair
     host:port code`. Success returns a persistent device fingerprint
     ("Successfully paired to 192.168.1.5:38571 [guid=adb-...]").
  4. After pairing, the phone shows a DIFFERENT port for the actual
     debug connection (e.g. 192.168.1.5:44121). User pastes that.
  5. POST /v1/mobile/connect {host, port} → runs `adb connect host:port`.
     From there the device appears in /v1/mobile/devices with serial
     `host:port` and everything else (screenshot, tap, etc.) works.

Security posture:
  * Both endpoints go through the same require_auth chain as the
    rest of /v1/mobile/*. The bearer token gates access.
  * Neither endpoint accepts arbitrary shell input — host and port
    are validated with a strict regex, code with `^\\d{6}$`.
  * We never persist the pairing code past the single `adb pair` call.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run

# host: IPv4 dotted quad or a hostname of allowed chars. IPv6 is not
# supported by `adb pair` / `adb connect` reliably (needs literal
# brackets and mDNS auto-resolution) so we don't advertise it.
_HOST_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.\-_]{0,253}$")
_CODE_RE = re.compile(r"^\d{6}$")


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def _validate_host_port(host: Any, port: Any) -> tuple[str, int] | dict[str, Any]:
    """Return (host, port) or an error dict."""
    if not isinstance(host, str) or not _HOST_RE.match(host):
        return _err(
            "invalid host",
            hint="Host must be an IPv4 address or hostname (a-z 0-9 . - _).",
        )
    try:
        p = int(port)
    except (TypeError, ValueError):
        return _err("port must be an integer")
    if p < 1 or p > 65535:
        return _err(f"port out of range: {p}")
    return (host, p)


def pair(host: str, port: int, code: str) -> dict[str, Any]:
    """`adb pair host:port code` — one-shot pairing handshake.

    The port here is the EPHEMERAL pairing port shown alongside the
    "Pair device with pairing code" dialog on Android, NOT the port
    the phone uses for the actual debug connection afterwards.
    """
    hp = _validate_host_port(host, port)
    if isinstance(hp, dict):
        return hp
    host, port = hp
    if not isinstance(code, str) or not _CODE_RE.match(code):
        return _err(
            "invalid code",
            hint="Pairing codes are 6 digits (e.g. 123456).",
        )
    guard = _ensure_adb()
    if guard:
        return guard

    target = f"{host}:{port}"
    try:
        # adb pair takes the code on stdin OR as the trailing arg; we
        # use the trailing arg because it works consistently across
        # adb 1.0.41+.
        r = run(["pair", target, code], timeout=30)
    except AdbNotFoundError as e:
        return _err(str(e))
    except subprocess.TimeoutExpired:
        return _err(
            "adb pair timed out",
            hint=(
                "Common causes: the pairing port on the phone expired "
                "(re-open the 'Pair device with pairing code' dialog), "
                "the phone is on a different subnet, or a firewall is "
                "blocking outbound TCP to the phone."
            ),
        )
    except Exception as e:
        return _err(f"adb pair failed: {e}")

    stdout = (r.stdout or "").strip()
    stderr = (r.stderr or "").strip()
    ok = (r.returncode == 0 and "Successfully paired" in stdout)
    if not ok:
        return _err(
            (stderr or stdout or f"adb pair exit {r.returncode}").strip() or "pairing failed",
            stdout=stdout, stderr=stderr, exit_code=r.returncode,
            hint=(
                "Double-check the 6-digit code on the phone. Codes "
                "expire after a minute or two — re-open the pairing "
                "dialog to get a fresh one."
            ),
        )
    return {
        "ok": True,
        "action": "pair",
        "host": host, "port": port,
        "stdout": stdout,
        "hint": (
            "Pairing succeeded. Now note the OTHER port shown on the "
            "phone under 'IP address & Port' (the wireless debugging "
            "connection port, NOT the pairing port) and call /connect "
            "with that."
        ),
    }


def connect(host: str, port: int = 5555) -> dict[str, Any]:
    """`adb connect host:port` — pick up a previously-paired device."""
    hp = _validate_host_port(host, port)
    if isinstance(hp, dict):
        return hp
    host, port = hp
    guard = _ensure_adb()
    if guard:
        return guard

    target = f"{host}:{port}"
    try:
        r = run(["connect", target], timeout=20)
    except AdbNotFoundError as e:
        return _err(str(e))
    except subprocess.TimeoutExpired:
        return _err(
            "adb connect timed out",
            hint="Phone unreachable — check Wi-Fi debugging is enabled "
                 "and the phone is on the same network.",
        )
    except Exception as e:
        return _err(f"adb connect failed: {e}")

    stdout = (r.stdout or "").strip()
    stderr = (r.stderr or "").strip()
    # `adb connect` reports success on stdout with "connected to ..."
    # or "already connected to ...". Failures like unauthorized come
    # back with returncode 0 too, so we need to parse the string.
    lower = stdout.lower()
    ok = ("connected to" in lower) and ("failed to connect" not in lower)
    if not ok:
        return _err(
            (stdout or stderr or f"adb connect exit {r.returncode}").strip() or "connect failed",
            stdout=stdout, stderr=stderr, exit_code=r.returncode,
            hint=(
                "If this is the first connect after a reboot, you'll "
                "need to re-pair (POST /v1/mobile/pair) because the "
                "phone regenerates its wireless debugging port. If it "
                "says 'unauthorized', tap 'Allow' on the phone's "
                "prompt."
            ),
        )
    return {
        "ok": True,
        "action": "connect",
        "host": host, "port": port,
        "serial": target,
        "stdout": stdout,
    }


def disconnect(host: str | None = None, port: int | None = None) -> dict[str, Any]:
    """`adb disconnect [host:port]` — drop one wireless device or all.

    Called with no args, disconnects every wireless device. USB-attached
    devices are unaffected either way — `adb disconnect` only touches
    TCP/IP transports.
    """
    args = ["disconnect"]
    if host is not None:
        hp = _validate_host_port(host, port or 5555)
        if isinstance(hp, dict):
            return hp
        host, port = hp
        args.append(f"{host}:{port}")
    guard = _ensure_adb()
    if guard:
        return guard
    try:
        r = run(args, timeout=10)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"adb disconnect failed: {e}")
    return {
        "ok": r.returncode == 0,
        "action": "disconnect",
        "target": args[1] if len(args) > 1 else "all",
        "stdout": (r.stdout or "").strip(),
        "stderr": (r.stderr or "").strip(),
        "exit_code": r.returncode,
    }
