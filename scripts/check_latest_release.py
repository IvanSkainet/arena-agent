#!/usr/bin/env python3
"""Print the latest release tag (without leading ``v``) for arena-agent
on GitHub, or a diagnostic hint to stderr and empty stdout if the query
fails. Called by ``install.bat`` / ``install.sh`` to compare against the
locally-installed bridge version.

Design rules (v4.60.12 replacement for an inline ``python -c "..."`` in
``install.bat`` that produced "Could not check GitHub — offline or
rate-limited" whenever GitHub anonymous rate limits kicked in):

1. **Redirect-fetch first** — ``https://github.com/<owner>/<repo>/releases/latest``
   is a 302 to ``/releases/tag/vX.Y.Z``. This path is NOT counted against
   the GitHub API rate limit (60/h anonymous), so it works even when
   the user has been running ``install.bat`` several times in an hour.

2. **API fallback with User-Agent + optional token** — if the redirect
   path fails, try the JSON API with a proper ``User-Agent`` (required
   by GitHub API) and, if ``GITHUB_TOKEN`` or ``GH_TOKEN`` is in the
   environment, add ``Authorization: token <...>`` which raises the
   rate limit to 5000/h.

3. **Precise hints on failure** — the caller (install.bat) used to print
   the generic "offline or rate-limited". This script distinguishes:
     - ``rate-limited (403 or 429)`` -> "set %GITHUB_TOKEN% to raise the limit"
     - network unreachable          -> "offline or firewall"
     - other HTTP error             -> the actual status code

Exit codes:
   0 = tag printed on stdout (may be empty if release list has no tags)
   1 = hint printed on stderr, stdout empty

Usage from install.bat::

    for /f "delims=" %%v in ('!PYTHON! "!BRIDGE_DIR!\\scripts\\check_latest_release.py"') do set "LATEST_VERSION=%%v"
"""
from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.request


DEFAULT_REPO = "IvanSkainet/arena-agent"
_TIMEOUT = 8


def _user_agent() -> str:
    """GitHub API refuses requests without an explicit User-Agent."""
    return "arena-agent-installer/1.0 (+https://github.com/IvanSkainet/arena-agent)"


def _token_from_env() -> str | None:
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "ARENA_GITHUB_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return None


def _fetch_via_redirect(repo: str) -> str | None:
    """Try ``/releases/latest`` which 302s to ``/releases/tag/vX.Y.Z``.

    NOT counted against the API rate limit (60/h anon) — this path
    survives repeated install.bat runs from the same IP.
    """
    url = f"https://github.com/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": _user_agent()},
    )
    try:
        # nosemgrep: dynamic-urllib-use-detected -- fixed prefix, no user input
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # nosec B310
            final = resp.geturl()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError):
        return None
    m = re.search(r"/releases/tag/v?([\d.]+[A-Za-z0-9.\-]*)/?$", final)
    if not m:
        return None
    return m.group(1)


def _fetch_via_api(repo: str, token: str | None) -> tuple[str | None, str | None]:
    """Return ``(tag, hint)``. ``tag`` is the latest release without the
    leading ``v``, or ``None`` on any failure. ``hint`` is a diagnostic
    string to print to stderr when tag is ``None`` (may itself be ``None``
    if there's nothing useful to say).
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {"User-Agent": _user_agent(), "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        # nosemgrep: dynamic-urllib-use-detected -- fixed prefix, no user input
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # nosec B310
            import json
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            hint = (
                "GitHub API rate limit exceeded (60/h anonymous). "
                "Set GITHUB_TOKEN (or GH_TOKEN) in the environment to raise it to 5000/h."
            )
            return None, hint
        return None, f"GitHub API returned HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return None, f"Network unreachable: {type(exc).__name__}"
    tag = str(data.get("tag_name", "")).lstrip("v")
    return (tag or None), None


def check(repo: str = DEFAULT_REPO) -> int:
    """Print the latest release tag or a diagnostic hint. Return an exit code."""
    # Path 1: redirect (rate-limit-immune)
    tag = _fetch_via_redirect(repo)
    if tag:
        print(tag)
        return 0
    # Path 2: API (with token if available)
    token = _token_from_env()
    tag, hint = _fetch_via_api(repo, token)
    if tag:
        print(tag)
        return 0
    if hint:
        sys.stderr.write(hint + "\n")
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    repo = DEFAULT_REPO
    if argv:
        # Optional first positional arg: <owner>/<repo>
        cand = argv[0].strip()
        if "/" in cand and cand.count("/") == 1:
            repo = cand
    return check(repo)


if __name__ == "__main__":
    raise SystemExit(main())
