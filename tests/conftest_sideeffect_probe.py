"""Probe v2: what actually opens a window or shows a toast?

v1 matched on substrings and produced a false positive: it flagged
`get_browsers()` because the PowerShell command it runs *contains* the
string `msedge.exe`, while the call only reads file version metadata
(verified on the host -- it returns the version and opens nothing).

This version classifies by what the command would *do*:
  * a browser executable invoked as the program itself (argv[0]), or
  * `start` / `explorer` / `os.startfile` handing a URL to the shell,
  * a real toast/notification API.
Everything else is recorded as OTHER so a miss is visible rather than
silently dropped.
"""
from __future__ import annotations

import os
import subprocess
import sys

_HITS: list[tuple[str, str, str]] = []
_CURRENT = {"id": "<none>"}

_BROWSER_EXE = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
                "chromium", "chrome", "msedge", "firefox", "opera.exe")
_SHELL_OPEN = ("startfile", "explorer.exe", "rundll32")
_NOTIFY = ("toastnotification", "notify-send", "osascript",
           "termux-notification", "windows.ui.notifications", "burnttoast")

_REAL_RUN = subprocess.run
_REAL_POPEN = subprocess.Popen


def _argv(cmd):
    if isinstance(cmd, (list, tuple)):
        return [str(c) for c in cmd]
    return [str(cmd)]


def _classify(cmd) -> str:
    argv = _argv(cmd)
    head = os.path.basename(argv[0]).lower() if argv else ""
    joined = " ".join(argv).lower()

    # A real toast: the notification API appears anywhere in the script.
    if any(w in joined for w in _NOTIFY):
        return "NOTIFICATION"
    # A browser launched as the program itself -- not merely named inside
    # a PowerShell string, which is what fooled v1.
    if any(head == b or head.startswith(b) for b in _BROWSER_EXE):
        return "BROWSER"
    if any(w in head for w in _SHELL_OPEN):
        return "BROWSER"
    # `cmd /c start <url>` and `powershell Start-Process <url>`.
    if "start-process" in joined or (head in ("cmd", "cmd.exe") and " start " in f" {joined} "):
        return "BROWSER"
    if "://" in joined and ("start" in joined or "open" in joined):
        return "BROWSER-MAYBE"
    return ""


def _note(cmd, how: str) -> None:
    kind = _classify(cmd)
    if kind:
        _HITS.append((kind, _CURRENT["id"], f"{how}: {' '.join(_argv(cmd))[:220]}"))


def _run(*args, **kwargs):
    _note(args[0] if args else kwargs.get("args", ""), "subprocess.run")
    return _REAL_RUN(*args, **kwargs)


class _Popen(_REAL_POPEN):  # type: ignore[misc,valid-type]
    def __init__(self, *args, **kwargs):
        _note(args[0] if args else kwargs.get("args", ""), "subprocess.Popen")
        super().__init__(*args, **kwargs)


subprocess.run = _run
subprocess.Popen = _Popen

_real_startfile = getattr(os, "startfile", None)
if _real_startfile is not None:                      # pragma: no cover - Windows
    def _spy_startfile(path, *a, **kw):
        _HITS.append(("BROWSER", _CURRENT["id"], f"os.startfile: {path}"))
        return _real_startfile(path, *a, **kw)
    os.startfile = _spy_startfile

try:                                                 # pragma: no cover
    import webbrowser

    _real_open = webbrowser.open

    def _spy_open(url, *a, **kw):
        _HITS.append(("BROWSER", _CURRENT["id"], f"webbrowser.open: {url}"))
        return _real_open(url, *a, **kw)

    webbrowser.open = _spy_open
    webbrowser.open_new = _spy_open
    webbrowser.open_new_tab = _spy_open
except Exception:
    pass


def pytest_runtest_setup(item):
    _CURRENT["id"] = item.nodeid


def pytest_sessionfinish(session, exitstatus):
    print(f"\nSIDE-EFFECT PROBE v2: {len(_HITS)} call(s)", file=sys.stderr)
    seen = set()
    for kind, test_id, what in _HITS:
        key = (kind, test_id)
        if key in seen:
            continue
        seen.add(key)
        print(f"  [{kind}] {test_id}\n      {what}", file=sys.stderr)
