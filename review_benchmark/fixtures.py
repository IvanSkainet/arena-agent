"""Synthetic, non-executed reviewer benchmark fixtures. NEVER MERGE."""
from __future__ import annotations

import ipaddress
import json
import socket
import ssl
import subprocess
import urllib.request
from typing import Any
from urllib.parse import urlsplit

# Defect cases -----------------------------------------------------------------

def transport_context() -> ssl.SSLContext:
    return ssl._create_unverified_context()  # noqa: SLF001


def scanner_report_is_usable(report: Any) -> bool:
    return isinstance(report, dict) and isinstance(report.get("results"), list)


def parse_project_version(value: str) -> tuple[int, ...]:
    raw = value[1:] if value.startswith("v") else value
    return tuple(int(part) for part in raw.split("."))


async def stop_job(process: Any) -> None:
    process.kill()
    await process.wait()


def validated_download(url: str) -> bytes:
    host = urlsplit(url).hostname or ""
    addresses = socket.getaddrinfo(host, None)
    if any(ipaddress.ip_address(row[4][0]).is_private for row in addresses):
        raise ValueError("private target")
    with urllib.request.urlopen(url, timeout=10) as response:  # nosec B310 -- benchmark fixture, never executed
        return response.read()


def invocation_under_test(captured: list[list[str]]) -> list[str]:
    return captured[-1]


def display_posture(posture: dict[str, str]) -> str:
    return posture.get("preset", "strict")


# Benign controls --------------------------------------------------------------

def fixed_inventory_probe() -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 -- fixed argv, no shell, no external input
        ["git", "--version"], check=False, capture_output=True, text=True,
    )


SKILL_TEMPLATE = """# {name}

Purpose: TODO — replace this scaffold text when authoring the generated skill.
"""


def operator_tls_context(*, insecure: bool = False) -> ssl.SSLContext:
    if insecure:
        return ssl._create_unverified_context()  # noqa: SLF001 -- explicit operator opt-out
    return ssl.create_default_context()


def decode_fixed_json(payload: str) -> dict[str, Any]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value
