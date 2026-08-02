"""Lifecycle operations against a declarative emulator provider.

Scope discipline: this module may only do things that ADB cannot. Booting
and killing a VM qualifies. Shell, screenshot, input, install and logcat do
not -- they are ADB, they already work against emulators and physical
phones alike, and they live in ``arena.mobile``. :func:`attach` exists to
hand the caller back to that domain rather than re-implement it here.
"""
from __future__ import annotations

import subprocess
import time
from typing import Any

from arena.emulator.providers import (
    EmulatorProvider,
    build_argv,
    detect_providers,
    find_provider,
    resolve_binary,
)

DEFAULT_TIMEOUT = 60


def _err(error: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": error}
    out.update(extra)
    return out


def _resolve(provider_id: str) -> tuple[EmulatorProvider, str] | dict[str, Any]:
    provider = find_provider(provider_id)
    if provider is None:
        known = sorted(p["id"] for p in detect_providers())
        return _err("unknown_provider", provider=provider_id, known_providers=known)
    binary = resolve_binary(provider)
    if binary is None:
        return _err(
            "provider_cli_not_found",
            provider=provider.id,
            hint=f"{provider.label} CLI not found on this host."
                 + (f" See {provider.docs}" if provider.docs else ""),
        )
    return provider, binary


def _run(argv: list[str], timeout: int) -> dict[str, Any]:
    """Run argv directly. No shell, no string interpolation."""
    try:
        cp = subprocess.run(  # nosec B603 -- argv list from a static provider table; shell is never used.
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout)),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "argv": argv, "timeout": timeout}
    except FileNotFoundError:
        return {"ok": False, "error": "executable_not_found", "argv": argv}
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "argv": argv}
    return {
        "ok": cp.returncode == 0,
        "returncode": cp.returncode,
        "argv": argv,
        "stdout": cp.stdout,
        "stderr": cp.stderr,
    }


def providers_report(*, host_os: str | None = None) -> dict[str, Any]:
    """Which emulator managers this host can drive."""
    rows = detect_providers(host_os=host_os)
    available = [r["id"] for r in rows if r["available"]]
    return {
        "ok": True,
        "providers": rows,
        "available": available,
        "count": len(rows),
        "note": (
            "Booting is provider-specific; everything after boot is ADB. "
            "Use mobile.* tools (mobile.devices, mobile.shell, mobile.screenshot, "
            "mobile.tap, ...) against the running instance -- they work for "
            "emulators and physical devices on every OS."
        ),
    }


def list_instances(*, provider: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Enumerate instances known to one provider.

    Output is left as raw text under ``stdout``: every vendor prints a
    different shape, and inventing a normalised schema we cannot verify on
    hosts we do not have would be a guess dressed up as a contract.
    """
    resolved = _resolve(provider)
    if isinstance(resolved, dict):
        return resolved
    prov, binary = resolved
    if not prov.list_argv:
        return _err("unsupported_operation", provider=prov.id, operation="list")
    res = _run([binary, *prov.list_argv], timeout)
    res["provider"] = prov.id
    return res


def start(*, provider: str, instance: str = "", timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Boot an instance. Returns as soon as the manager's verb returns."""
    resolved = _resolve(provider)
    if isinstance(resolved, dict):
        return resolved
    prov, binary = resolved
    if not prov.start_argv:
        return _err("unsupported_operation", provider=prov.id, operation="start")
    argv = [binary, *build_argv(prov, prov.start_argv, instance)]
    res = _run(argv, timeout)
    res["provider"] = prov.id
    res["instance"] = instance
    res["next"] = "Poll mobile.devices until the instance appears, then drive it with mobile.* tools."
    return res


def stop(*, provider: str, instance: str = "", timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Shut an instance down through the provider's own verb.

    Providers with no stop verb (the AOSP emulator, for one) report
    ``unsupported_operation`` with the ADB route spelled out, rather than
    us guessing at a kill.
    """
    resolved = _resolve(provider)
    if isinstance(resolved, dict):
        return resolved
    prov, binary = resolved
    if not prov.stop_argv:
        return _err(
            "unsupported_operation",
            provider=prov.id,
            operation="stop",
            hint="This manager has no stop verb. Use mobile.shell with `reboot -p`, "
                 "or `adb -s <serial> emu kill` for AOSP AVDs.",
        )
    argv = [binary, *build_argv(prov, prov.stop_argv, instance)]
    res = _run(argv, timeout)
    res["provider"] = prov.id
    res["instance"] = instance
    return res


def attach(*, serial_hint: str = "", wait_s: int = 0, poll_s: float = 1.0) -> dict[str, Any]:
    """Report ADB-visible devices so the caller can hand off to ``mobile.*``.

    This deliberately adds nothing on top of ``arena.mobile.devices`` beyond
    optional waiting: the point is to end the emulator-specific path, not to
    grow a second device API next to the one that already exists.
    """
    try:
        from arena.mobile.devices import list_devices
    except Exception as exc:  # pragma: no cover - mobile domain always present
        return _err(f"mobile_domain_unavailable: {type(exc).__name__}: {exc}")

    deadline = time.monotonic() + max(0, int(wait_s))
    snapshot: dict[str, Any] = {}
    while True:
        snapshot = list_devices()
        devices = snapshot.get("devices") or []
        if serial_hint:
            devices = [d for d in devices if serial_hint in str(d.get("serial", ""))]
        if devices or time.monotonic() >= deadline:
            return {
                "ok": bool(devices),
                "devices": devices,
                "adb_installed": snapshot.get("adb_installed"),
                "hint": snapshot.get("hint"),
                "waited_s": max(0, int(wait_s)) if not devices else None,
                "next": "Drive the device with mobile.shell / mobile.screenshot / mobile.tap / mobile.install.",
            }
        time.sleep(max(0.05, float(poll_s)))


__all__ = ["attach", "list_instances", "providers_report", "start", "stop"]
