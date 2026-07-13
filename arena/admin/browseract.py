"""BrowserAct admin runtime helpers.

BrowserAct is a stealth-aware browser automation CLI (browser-act-cli on
PyPI) that Arena skills use for scraping/interaction tasks. This module
gives the Bridge a cross-platform, provider-agnostic view of the tool so
the dashboard and /v1/capabilities can report whether it is installed,
which version, and how to update — without any assumption about how the
user installed it (uv tool, pipx, manual venv, etc.).

Cross-platform contract:

  * Windows: prefers browser-act.exe from PATH; also checks the standard
    uv-tool bin path under %USERPROFILE% and the pipx bin dir.
  * macOS / Linux: prefers `browser-act` from PATH; also checks common uv
    and pipx locations.
  * The module never invokes package managers; it only reports install
    location, version, and an actionable install/update hint.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from typing import Any


DEFAULT_TIMEOUT = 10
UPSTREAM_PACKAGE = "browser-act-cli"


# ---------------------------------------------------------------------------
# CLI discovery
# ---------------------------------------------------------------------------
def _cli_candidates() -> list[str]:
    system = platform.system().lower()
    names = ["browser-act"]
    if system == "windows":
        names = ["browser-act.exe", "browser-act.bat", "browser-act.cmd", "browser-act"]

    candidates: list[str] = []
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(found)

    home = os.path.expanduser("~")
    if system == "windows":
        # uv tool default install location on Windows.
        candidates += [
            os.path.join(home, ".local", "bin", "browser-act.exe"),
            os.path.join(home, "AppData", "Roaming", "uv", "tools", "browser-act-cli", "Scripts", "browser-act.exe"),
            os.path.join(home, "AppData", "Local", "pipx", "venvs", "browser-act-cli", "Scripts", "browser-act.exe"),
        ]
    else:
        # uv + pipx common paths.
        candidates += [
            os.path.join(home, ".local", "bin", "browser-act"),
            os.path.join(home, ".local", "share", "uv", "tools", "browser-act-cli", "bin", "browser-act"),
            os.path.join(home, ".local", "pipx", "venvs", "browser-act-cli", "bin", "browser-act"),
            "/usr/local/bin/browser-act",
            "/opt/homebrew/bin/browser-act",
        ]

    seen: set[str] = set()
    out: list[str] = []
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            out.append(path)
    return out


def _cli_source(path: str) -> str:
    if "uv/tools" in path or "\\uv\\tools\\" in path or "\\uv/tools/" in path:
        return "uv-tool"
    if "pipx" in path.lower():
        return "pipx"
    lower = path.lower()
    if lower.endswith(".local/bin/browser-act") or lower.endswith(r".local\bin\browser-act.exe"):
        return "uv-tool"  # uv creates the .local/bin symlink by default
    if lower.startswith("/usr/local/") or lower.startswith("/opt/homebrew/"):
        return "system"
    return "unknown"


def _get_version(cli_path: str) -> str | None:
    try:
        proc = subprocess.run(
            [cli_path, "--version"],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip() + " " + (proc.stderr or "").strip()
    # Common formats: "browser-act 2.0.2", "browser-act, version 2.0.2".
    import re
    m = re.search(r"([0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.\-]*)?)", out)
    return m.group(1) if m else out.split()[-1] if out.strip() else None


# ---------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------
def _install_hint() -> str:
    system = platform.system().lower()
    if system == "windows":
        return (
            f"Install BrowserAct CLI: `winget install --id=astral-sh.uv` "
            f"then `uv tool install {UPSTREAM_PACKAGE} --python 3.12`. "
            f"See https://www.browseract.com/ for docs."
        )
    if system == "darwin":
        return (
            f"Install BrowserAct CLI: `brew install uv` "
            f"then `uv tool install {UPSTREAM_PACKAGE} --python 3.12`. "
            f"See https://www.browseract.com/ for docs."
        )
    return (
        f"Install BrowserAct CLI: install uv "
        f"(https://docs.astral.sh/uv/getting-started/installation/) "
        f"then `uv tool install {UPSTREAM_PACKAGE} --python 3.12`. "
        f"See https://www.browseract.com/ for docs."
    )


def _update_hint(source: str) -> str:
    if source == "uv-tool":
        return f"Update via: `uv tool upgrade {UPSTREAM_PACKAGE}`"
    if source == "pipx":
        return f"Update via: `pipx upgrade {UPSTREAM_PACKAGE}`"
    if source == "system":
        return "Update via your package manager (or reinstall with the tool of your choice)."
    return f"Reinstall the CLI to update: `uv tool install --force {UPSTREAM_PACKAGE} --python 3.12`"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def browseract_status(*, subprocess_kwargs=None) -> dict[str, Any]:
    """Return BrowserAct install/version status in a stable, cross-platform shape."""
    system = platform.system().lower()
    result: dict[str, Any] = {
        "ok": True,
        "installed": False,
        "cli_path": None,
        "cli_source": None,
        "version": None,
        "platform": system,
        "hint": None,
    }
    candidates = _cli_candidates()
    if not candidates:
        result["ok"] = False
        result["hint"] = _install_hint()
        return result

    cli = candidates[0]
    result["installed"] = True
    result["cli_path"] = cli
    result["cli_source"] = _cli_source(cli)
    result["version"] = _get_version(cli)
    result["update_hint"] = _update_hint(result["cli_source"])
    return result


def browseract_doctor(*, subprocess_kwargs=None) -> dict[str, Any]:
    """Deeper self-check: version + handshake with the tool's own skill manifest."""
    status = browseract_status(subprocess_kwargs=subprocess_kwargs)
    if not status.get("installed"):
        return {**status, "handshake": False, "error": "browser-act not installed"}

    cli = status["cli_path"]
    handshake_ok = False
    handshake_error = None
    try:
        proc = subprocess.run(
            [cli, "get-skills", "core", "--skill-version", "2.0.0"],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
        )
        if proc.returncode == 0 and proc.stdout:
            handshake_ok = True
        else:
            handshake_error = (proc.stderr or proc.stdout or f"exit={proc.returncode}").strip()[:500]
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        handshake_error = str(e)

    return {
        **status,
        "handshake": handshake_ok,
        "handshake_error": handshake_error,
    }
