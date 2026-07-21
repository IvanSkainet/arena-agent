"""Windows service/task helper functions for bridge service runtime."""
from __future__ import annotations

import json
import subprocess
import sys

from arena.util import _subprocess_kwargs


def _ps_utf8_command(script: str) -> list[str]:
    prefix = (
        "$OutputEncoding = [Console]::OutputEncoding = "
        "[System.Text.UTF8Encoding]::new($false); "
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
    )
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", prefix + script]

def _windows_scheduled_task_info(task_name: str) -> dict:
    """Return schtasks info for `task_name`.

    v4.60.3 field-observation update: many Windows installs use a task
    that launches a helper (e.g. start_hidden.vbs) which spawns the
    bridge Python and exits. In that pattern schtasks reports the task
    as "Ready" (English) / "Готово" (Russian) / "Bereit" (German) /
    etc. AFTER a successful launch — never as "Running" — even though
    the bridge itself is alive as a detached process. The old strict
    "running" substring check made Doctor report DOWN in exactly this
    common case.

    New logic:
      * exists = schtasks /Query exit code 0
      * last_result_code = parsed from "Last Result Code" / localized label
      * running = literal running/выполня/... substring   -- OR --
                  (exists AND last_result_code == 0)  -- successful launcher
    """
    info = {"exists": False, "running": False, "raw": "",
            "last_result_code": None}
    try:
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST", "/V"],
            capture_output=True, text=True, timeout=8, **_subprocess_kwargs(),
        )
        raw = (r.stdout or "") + (r.stderr or "")
        info["raw"] = raw[:1200]
        info["exists"] = (r.returncode == 0)

        low = raw.lower()
        # Literal-execution substrings, per locale. RUNNING and Ready are
        # always English in schtasks /FO LIST output on some Windows builds
        # but on many localized builds the value field itself is translated.
        running_substrings = (
            "running",     # en
            "выполня",     # ru "выполняется"
            "wird ausge",  # de "wird ausgeführt"
            "en cours",    # fr
            "en ejec",     # es
            "in esec",     # it
            "実行",         # ja
            "运行",         # zh
        )
        info["running"] = any(sub in low for sub in running_substrings)

        # Parse "Last Result" numeric code. Line label is localized; the
        # value on the right of ':' is a small integer (0 == success, or
        # 0x41300 == "task has not yet run", etc). We scan every colon-
        # delimited line and take the last small-int match; safer than
        # matching a localized label.
        last_code = None
        for line in raw.splitlines():
            if ":" not in line:
                continue
            _label, _, value = line.partition(":")
            value = value.strip()
            if not value:
                continue
            # value can be "0" or "0x41300" or "-1" — accept int()/int(,16)
            try:
                if value.lower().startswith("0x"):
                    n = int(value, 16)
                else:
                    n = int(value)
                # heuristic: constrain to plausible exit codes so we don't
                # capture PIDs, RAM sizes, dates etc.
                if -256 <= n <= 0x7FFFFFFF:
                    last_code = n
            except (ValueError, TypeError):
                continue
        info["last_result_code"] = last_code

        # v4.60.3: successful-launcher fallback. If the task ran and
        # returned 0, and we don't have literal "running" text, treat
        # it as healthy. Doctor also checks bridge_processes count > 0
        # separately, so this only marks the schtasks entry itself as
        # OK — not the entire bridge.
        if not info["running"] and info["exists"] and last_code == 0:
            info["running"] = True
            info["running_reason"] = "launcher-exit-0"
    except Exception as e:
        info["error"] = str(e)[:200]
    return info

def _windows_bridge_processes() -> list[dict]:
    """Return matching Python bridge/helper processes with command lines."""
    if sys.platform != "win32":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
        "Where-Object { $_.CommandLine -match 'arena|bridge|unified_bridge|local_bridge|mcp_ws|web_gateway|agentctl' } | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress -Depth 4"
    )
    try:
        r = subprocess.run(_ps_utf8_command(ps), capture_output=True, text=True, timeout=10, **_subprocess_kwargs())
        out = (r.stdout or "").strip()
        if not out:
            return []
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        procs = []
        for item in data:
            cmd = str(item.get("CommandLine") or "")
            role = "helper"
            if "unified_bridge.py" in cmd and " serve" in cmd:
                role = "main-bridge"
            elif "unified_bridge" in cmd:
                role = "bridge-related"
            procs.append({
                "pid": item.get("ProcessId"),
                "ppid": item.get("ParentProcessId"),
                "name": item.get("Name"),
                "role": role,
                "command_line": cmd[:1000],
            })
        return procs
    except Exception:
        return []

def _sc_query_running(svc_name: str) -> tuple[bool, str, bool]:
    """Run `sc query <name>` and return (exists, raw_output, running).
    Locale-agnostic: looks for the numeric state code `STATE` line containing
    "4" (RUNNING), in addition to any RUNNING substring.
    """
    try:
        r = subprocess.run(
            ["sc", "query", svc_name],
            capture_output=True, text=True, timeout=5,
            **_subprocess_kwargs(),
        )
    except Exception:
        return False, "", False
    out = (r.stdout or "") + (r.stderr or "")
    # `sc query` exits 1060 (ERROR_SERVICE_DOES_NOT_EXIST) -> no service
    if r.returncode == 1060 or "1060" in out:
        return False, out, False
    # Locale-agnostic checks
    # English: "STATE              : 4  RUNNING"
    # Russian: "Состояние          : 4  RUNNING"   (RUNNING is always English)
    # German:  "ZUSTAND            : 4  RUNNING"
    # Italian: "STATO              : 4  RUNNING"
    # etc. — "RUNNING" is constant; numeric state code `: 4 ` is constant.
    up = out.upper()
    running = ("RUNNING" in up) or (": 4 " in out) or (": 4\t" in out)
    # heuristic: presence of "_NAME" / numeric STATE row means service exists
    exists = (": 4 " in out) or (": 1 " in out) or (": 2 " in out) or (": 3 " in out) \
             or (": 5 " in out) or (": 6 " in out) or (": 7 " in out) \
             or ("RUNNING" in up) or ("STOPPED" in up) or ("PAUSED" in up) \
             or ("PENDING" in up)
    return exists, out, running

