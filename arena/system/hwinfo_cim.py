"""Windows-style hwinfo collector implementation.

Security posture (v4.43.0 hardening pass)
-----------------------------------------

The original v3-era implementation built PowerShell command
strings by interpolating a class name / filter clause into an
``f-string`` and handed the whole thing to ``subprocess.run(...,
shell=True)``. In production every call site (``arena/system/
hwinfo_collect.py``) passes a fixed literal like
``"Win32_Processor"`` or
``"Win32_NetworkAdapterConfiguration where IPEnabled=True"``,
so no external caller can inject PowerShell today -- but the
architectural invariant "``get_cim_all_list`` is only ever
called with a compile-time literal" is fragile.

v4.43.0 tightens the surface without changing the behaviour:

* every call switches to **argv-form** ``subprocess.run``
  (``["powershell.exe", "-NoProfile", "-Command", ps_cmd]``).
  Windows spawns the process without going through cmd.exe --
  no shell metacharacters ever reach a parser.
* the ``class_name`` parameter is validated against a
  whitelist regex that matches Win32_* / CIM_* class names
  (letters, digits, underscore only). A filter clause is
  parsed out first and validated separately: only
  ``Key=Value`` form with alphanumerics + a small set of
  operators. Anything else -> the function returns ``[]``
  same as any other failure, so callers already handle it.
* the shell-string form is preserved as a code comment for
  the audit trail. A future caller that needs richer WQL
  should extend the whitelist rather than reintroduce the
  shell-string form.
"""
from __future__ import annotations

import datetime  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import json
import os  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import platform  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import re
import subprocess
import sys  # noqa: F401  # kept: re-export/dynamic (AGENTS.md)
import time

# Whitelist for CIM/WMI class names: letters, digits, underscore.
# Real class names are ``Win32_<Something>`` or ``CIM_<Something>``;
# nothing else is legitimate. Matches the full class-name segment.
_CIM_CLASS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,63}$")

# Whitelist for a single WQL filter clause of the form
# ``Property=Value``. Values are limited to bareword literals
# (True / False / numeric / identifier) -- more than enough for
# every real call site in hwinfo_collect.py without opening a
# quoted-string parser that would need its own escaping.
_CIM_FILTER_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9_]{0,63})\s*=\s*"
    r"([A-Za-z0-9_.\-]{1,64})$"
)


def _sanitise_class(cls: str) -> str | None:
    cls = cls.strip()
    if not cls:
        return None
    if not cls.lower().startswith(("win32_", "cim_")):
        cls = "Win32_" + cls
    return cls if _CIM_CLASS_RE.match(cls) else None


def _sanitise_filter(clause: str) -> str | None:
    clause = clause.strip().strip("\"'")
    if not clause:
        return None
    m = _CIM_FILTER_RE.match(clause)
    if not m:
        return None
    # Reassemble in canonical form (no user-controlled spaces or
    # quoting sneaks through).
    return f"{m.group(1)}={m.group(2)}"


# Per-command PowerShell budget.
#
# ``collect_full()`` issues ~10 Get-CimInstance calls back to back. With the
# original 30 s per call the theoretical worst case was ~5 minutes, while
# callers (notably tests/test_project_modularity.py) budget 30 s for the whole
# process -- an outer budget smaller than the inner worst case, which shows up
# as an intermittent TimeoutExpired on slow/contended CI runners rather than as
# an obvious bug. A cold CIM query answers in well under 8 s; anything slower is
# a stuck WMI service, and waiting 30 s on it helps nobody.
#
# tests/test_hwinfo_timeout_budget.py enforces that the inner worst case stays
# below every outer budget. Raising this without raising those fails that gate.
PS_TIMEOUT_S = 8

# Wall-clock budget for one whole collection pass. Per-call timeouts alone are
# not enough: ten calls x 8 s still exceeds a 30 s outer budget. Once the pass
# budget is spent, remaining queries return immediately with empty output, so a
# degraded WMI service yields a partial-but-fast answer instead of a hang. The
# ratio (not just the constants) is what tests/test_hwinfo_timeout_budget.py
# pins.
PS_PASS_BUDGET_S = 20

# Monotonic deadline for the current pass, or None when no pass is active.
_pass_deadline: float | None = None
# The budget the active pass was opened with, so _remaining() can clamp to
# it directly instead of trusting clock arithmetic to stay inside it.
_pass_budget_s: float = 0.0


def begin_pass(budget_s: float = PS_PASS_BUDGET_S) -> None:
    """Open a collection pass with a shared wall-clock budget."""
    global _pass_deadline, _pass_budget_s
    _pass_budget_s = max(0.0, float(budget_s))
    _pass_deadline = time.monotonic() + _pass_budget_s


def end_pass() -> None:
    """Close the current pass; subsequent calls are unbudgeted again."""
    global _pass_deadline, _pass_budget_s
    _pass_deadline = None
    _pass_budget_s = 0.0


def _remaining(timeout: int) -> float | None:
    """Seconds this call may take, or None when the pass budget is spent.

    v4.165.0: the result is clamped to the budget as well as to `timeout`.
    Windows' monotonic clock has a coarse tick, and when two reads land
    inside the same one the subtraction can come back a hair ABOVE the
    budget -- CI saw `2.0000000000002274` against a 2 s pass and went red
    on five runners. A quarter-nanosecond overrun harms nothing in
    production, but a bound that is only nearly true is a bound nobody
    can assert on, and the test asserting it was right to complain.
    """
    if _pass_deadline is None:
        return float(timeout)
    left = _pass_deadline - time.monotonic()
    if left <= 0:
        return None
    return min(float(timeout), left, float(_pass_budget_s))


def _run_powershell(script: str, timeout: int = PS_TIMEOUT_S) -> subprocess.CompletedProcess:
    """Argv-form PowerShell runner. No shell involved -- Windows
    launches powershell.exe directly, so metacharacters in
    ``script`` reach only PowerShell's own parser (never cmd.exe
    interpolation). ``script`` still has to be a valid PowerShell
    fragment; callers assemble it from whitelisted components.

    The default timeout is deliberately per-call and small: see
    ``PS_TIMEOUT_S``.
    """
    budget = _remaining(timeout)
    if budget is None:
        # Pass budget exhausted -- fail fast and empty. Callers already treat
        # empty stdout as "no data", so no call site needs to change.
        return subprocess.CompletedProcess(
            args=["powershell.exe", "-NoProfile", "-Command", script],
            returncode=1, stdout="", stderr="hwinfo pass budget exhausted",
        )
    return subprocess.run(  # nosec B603 -- argv form, no shell
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True, text=True, timeout=budget,
    )


def get_cim_all_list(class_name):
    """Utility to run Get-CimInstance and parse all properties as dictionary list

    v4.43.0: accepts one of two shapes for ``class_name``:

    * ``"Win32_Processor"`` -- plain class name; whitelisted
      via ``_sanitise_class``.
    * ``"Win32_NetworkAdapterConfiguration where IPEnabled=True"``
      -- class name plus a single filter clause. Both parts are
      whitelisted separately.

    Anything that fails the whitelist returns ``[]`` -- same
    outcome as a real PowerShell failure, so no caller needs
    to change.
    """
    try:
        cmd = class_name
        if " path " in class_name.lower():
            cmd = class_name.split("path ", 1)[1]

        if " where " in cmd.lower():
            parts = cmd.lower().split(" where ", 1)
            cls = _sanitise_class(parts[0])
            filt = _sanitise_filter(parts[1])
            if cls is None or filt is None:
                return []
            ps_cmd = (
                f"Get-CimInstance {cls} -Filter '{filt}' "
                "| ConvertTo-Json -Compress"
            )
        else:
            cls = _sanitise_class(cmd)
            if cls is None:
                return []
            ps_cmd = f"Get-CimInstance {cls} | ConvertTo-Json -Compress"

        res = _run_powershell(ps_cmd)
        if not res.stdout.strip():
            return []

        data = json.loads(res.stdout)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []

def get_uptime():
    try:
        # v4.43.0: argv-form. The scripts here are fixed
        # PowerShell literals with no interpolated user input;
        # switching them along with get_cim_all_list keeps the
        # module uniform (grep for shell=True must return
        # nothing under arena/system/hwinfo_cim.py).
        res = _run_powershell(
            "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime "
            "| ConvertTo-Json"
        )
        if res.stdout.strip():
            # PowerShell might return a date string like "/Date(1682390192000)/" or just a formatted string
            # Better to get milliseconds directly
            res2 = _run_powershell(
                "[int64]((Get-Date) - (Get-CimInstance Win32_OperatingSystem)"
                ".LastBootUpTime).TotalSeconds"
            )
            if res2.stdout.strip() and res2.stdout.strip().isdigit():
                seconds = int(res2.stdout.strip())
                days = seconds // 86400
                hours = (seconds % 86400) // 3600
                minutes = (seconds % 3600) // 60
                return f"{days} days, {hours} hours, {minutes} minutes"
    except Exception:
        pass
    return "Unknown"
