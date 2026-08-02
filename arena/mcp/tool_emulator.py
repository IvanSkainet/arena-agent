"""MCP surface for provider-agnostic Android emulator control.

Replaces the vendor-locked ``mumu.*`` namespace (v4.155.0). Five tools, no
vendor in any name: which managers exist here, what instances they hold,
boot, shut down, and hand off to ADB. MuMu survives only as one row in a
data table alongside AVD, Genymotion and Waydroid.
"""
from __future__ import annotations

import json
from typing import Any

from arena.emulator import control
from arena.mcp.tool_utils import text_content


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_emulator_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if not name.startswith("emulator."):
        return None

    timeout = int(args.get("timeout", control.DEFAULT_TIMEOUT) or control.DEFAULT_TIMEOUT)
    provider = str(args.get("provider") or "").strip()
    instance = str(args.get("instance", "")).strip()

    if name == "emulator.providers":
        return _ok(control.providers_report())

    if name in {"emulator.list", "emulator.start", "emulator.stop"} and not provider:
        return _ok({
            "ok": False,
            "error": "provider is required",
            "hint": "Call emulator.providers first to see which managers this host can drive.",
        })

    if name == "emulator.list":
        return _ok(control.list_instances(provider=provider, timeout=timeout))
    if name == "emulator.start":
        return _ok(control.start(provider=provider, instance=instance, timeout=timeout))
    if name == "emulator.stop":
        return _ok(control.stop(provider=provider, instance=instance, timeout=timeout))
    if name == "emulator.attach":
        return _ok(control.attach(
            serial_hint=str(args.get("serial_hint", "")).strip(),
            wait_s=int(args.get("wait_s", 0) or 0),
        ))
    return None


_TIMEOUT_PROP = {"type": "integer", "default": control.DEFAULT_TIMEOUT, "description": "Seconds before the provider CLI call is killed."}
_PROVIDER_PROP = {"type": "string", "description": "Provider id from emulator.providers (e.g. avd, genymotion, mumu, waydroid)."}
_INSTANCE_PROP = {"type": "string", "description": "Instance id as the provider names it (AVD name, VM index, ...). Omit for single-session providers."}

EMULATOR_TOOLS = [
    {
        "name": "emulator.providers",
        "description": (
            "List every known Android emulator manager and whether this host can drive it. "
            "Start here: emulator support is host-dependent. Post-boot control is plain ADB via mobile.* tools."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "emulator.list",
        "description": "List instances known to one emulator provider. Raw provider output; shapes differ per vendor.",
        "inputSchema": {
            "type": "object",
            "properties": {"provider": _PROVIDER_PROP, "timeout": _TIMEOUT_PROP},
            "required": ["provider"],
            "additionalProperties": False,
        },
    },
    {
        "name": "emulator.start",
        "description": "Boot an emulator instance, then poll mobile.devices and drive it with mobile.* tools.",
        "inputSchema": {
            "type": "object",
            "properties": {"provider": _PROVIDER_PROP, "instance": _INSTANCE_PROP, "timeout": _TIMEOUT_PROP},
            "required": ["provider"],
            "additionalProperties": False,
        },
    },
    {
        "name": "emulator.stop",
        "description": "Shut an emulator instance down via its provider's own verb. Reports unsupported_operation when the manager has none.",
        "inputSchema": {
            "type": "object",
            "properties": {"provider": _PROVIDER_PROP, "instance": _INSTANCE_PROP, "timeout": _TIMEOUT_PROP},
            "required": ["provider"],
            "additionalProperties": False,
        },
    },
    {
        "name": "emulator.attach",
        "description": "Return ADB-visible devices, optionally waiting for one to appear after a boot. Hand-off point to the mobile.* toolset.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "serial_hint": {"type": "string", "description": "Substring filter over ADB serials."},
                "wait_s": {"type": "integer", "default": 0, "description": "Seconds to keep polling for a matching device."},
            },
            "additionalProperties": False,
        },
    },
]


__all__ = ["EMULATOR_TOOLS", "handle_emulator_tool"]
