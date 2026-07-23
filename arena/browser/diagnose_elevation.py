"""v4.60.20 - capture known Chromium/Edge elevated-warning in stderr.

When Edge (or Chrome) is launched from an admin/elevated process on
Windows, Chromium emits a single WARNING line on stderr and then
**silently exits without doing anything**. This is by design
(upstream Chromium security policy: headless from admin is
forbidden). It looks like the bridge is broken, but the cause is
external.

This helper extracts the elevated-warning marker from stderr (or any
other Chromium "I refuse to run" messages) and returns a structured
``isError`` dict with an actionable hint. It is **diagnostic-only**:
it does not try to work around the upstream policy (we cannot
un-elevate a service), it just makes the failure visible.

Use case:
    subprocess.Popen(...) -> run for N seconds -> exit 0, stdout empty
    -> call this helper on stderr -> emit isError with
       "Edge is running elevated: 1. See docs/browser-headless-on-windows.md"
"""
from __future__ import annotations

import re
from typing import Optional

# Pattern that Chromium's chrome_browser_main_win.cc emits. We match
# "running elevated" + numeric elevation indicator (1 == elevated).
ELEVATED_RE = re.compile(
    r"running\s+elevated\s*[:=]\s*1",
    re.IGNORECASE,
)

# Other known "I refuse" markers (not exhaustive, just common ones
# we'd like to surface rather than let the user debug by reading
# raw stderr).
KNOWN_REFUSALS = [
    (re.compile(r"running\s+elevated\s*[:=]\s*1", re.I),
     "Edge is running elevated: 1. Headless mode from an admin process is "
     "blocked by Chromium's security policy. Workarounds: "
     "(1) run the bridge as a non-admin service; "
     "(2) use BrowserAct's cloud browser; "
     "(3) install Camoufox (Firefox-based, no elevation block) and use "
     "`browser.launch --type=camoufox` instead of Edge. "
     "See docs/browser-headless-on-windows.md for details."),
    (re.compile(r"elevation\s+is\s+not\s+supported", re.I),
     "Edge refused to start headless: elevation is not supported. "
     "Same workarounds as the 'running elevated' warning above."),
]


def diagnose_browser_stderr(stderr: str) -> Optional[dict]:
    """Look for known Chromium/Edge "I refuse" markers in `stderr`.

    Returns ``None`` if stderr looks healthy (no refusals found).
    Returns a structured ``isError`` dict with a clear message and
    a pointer to the docs file if a known refusal is detected.
    """
    if not stderr:
        return None
    for pat, message in KNOWN_REFUSALS:
        if pat.search(stderr):
            return {
                "isError": True,
                "content": [{"type": "text", "text": message}],
            }
    return None


def diagnose_browser_exit(
    *,
    return_code: int,
    stdout: str,
    stderr: str,
    expected_output_substr: str = "",
) -> Optional[dict]:
    """Combine exit code + stdout/stderr to produce a structured
    ``isError`` if the browser invocation looks unhealthy.

    Heuristics:
      * empty stdout + empty stderr + rc=0 -> "started but produced
        nothing" (often a sign of the elevated-warning abort).
      * ``expected_output_substr`` provided but not found -> mismatch.
      * known refusals (see ``diagnose_browser_stderr``).
    """
    refusal = diagnose_browser_stderr(stderr)
    if refusal is not None:
        return refusal
    if expected_output_substr and expected_output_substr not in stdout:
        return {
            "isError": True,
            "content": [{
                "type": "text",
                "text": (
                    f"Browser exited with code {return_code} but stdout did "
                    f"not contain expected substring {expected_output_substr!r}. "
                    f"stdout[:200]={stdout[:200]!r} stderr[:200]={stderr[:200]!r}"
                ),
            }],
        }
    if return_code == 0 and not stdout.strip() and not stderr.strip():
        return {
            "isError": True,
            "content": [{
                "type": "text",
                "text": (
                    "Browser exited cleanly (rc=0) but produced no output. "
                    "Common causes: (1) elevated admin process on Windows "
                    "(see 'running elevated' warning); (2) missing user-data-dir "
                    "writable by the bridge's user; (3) page didn't load within "
                    "the navigation timeout. See docs/browser-headless-on-windows.md."
                ),
            }],
        }
    return None
