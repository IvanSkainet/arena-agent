"""GitHub-specific helpers for auto-update (v3.86.2).

Extracted from arena.admin.auto_update to keep that module below the
600-line per-file limit. Everything here talks to `api.github.com`,
`github.com` or `raw.githubusercontent.com`. Public surface:

  * `github_token()` -- returns GITHUB_TOKEN or GH_TOKEN if set
  * `http_get_json(url)` -- authenticated GET if a token is present
  * `pick_asset(assets)` -- prefer the versioned zip over the alias
  * `fetch_asset_size(url)` -- HEAD an asset URL for Content-Length
  * `fetch_changelog_section(repo, tag)` -- pull the CHANGELOG.md
    block for the given tag via raw.githubusercontent.com (no rate limit)
  * `resolve_latest_via_redirect(repo)` -- read the tag out of the
    /releases/latest 302 Location, zero API quota cost

None of these ever raise -- callers get None or an empty result on
network / rate-limit / parse errors.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


_USER_AGENT_PREFIX = "arena-agent-auto-update"
_HTTP_TIMEOUT = 15


def _user_agent() -> str:
    """Runtime user-agent -- pulls the bridge version at call time so
    a rolling upgrade sees the fleet-mix bump immediately."""
    try:
        from arena.constants import VERSION
        return f"{_USER_AGENT_PREFIX}/{VERSION}"
    except Exception:
        return _USER_AGENT_PREFIX


def _token_file_path():
    """v4.50.0: <install_root>/.github_token stores a UI-configured
    token. Dot-file so a self-update never overwrites it (dotfiles
    are not in the update replace-targets list). Import lives here
    (deferred) to avoid an auto_update <-> update_github import cycle.
    Returns None when the file is not present or unreadable."""
    try:
        from arena.admin.auto_update import _install_root
        return _install_root() / ".github_token"
    except Exception:
        return None


def _read_token_file() -> str | None:
    p = _token_file_path()
    if not p or not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not text:
        return None
    # First non-empty non-comment line. Guards against operators
    # pasting multi-line blobs, and lets a "# ..." header sit above.
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def github_token() -> str | None:
    """Precedence: GITHUB_TOKEN env > GH_TOKEN env > UI-saved
    <install_root>/.github_token. Whitespace-only values are treated
    as unset. v4.50.0: file-backed fallback lets Windows operators
    configure the token from the dashboard without editing nssm's
    Environment tab or systemd overrides."""
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(name)
        if v and v.strip():
            return v.strip()
    return _read_token_file()


def github_token_source() -> str:
    """Returns 'env' / 'file' / 'none' so the UI can show where
    the currently active token was resolved from."""
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(name)
        if v and v.strip():
            return "env"
    if _read_token_file():
        return "file"
    return "none"


def save_github_token(raw: str) -> dict:
    """Atomically write the operator-supplied token to
    <install_root>/.github_token with 0600 permissions. Called by
    /v1/admin/update/token-set. Never logs the token itself."""
    p = _token_file_path()
    if p is None:
        return {"ok": False, "error": "install root not resolvable; "
                "cannot decide where to store the token"}
    token = (raw or "").strip()
    if not token:
        return {"ok": False, "error": "token is empty"}
    if any(c.isspace() for c in token):
        return {"ok": False, "error": "token contains whitespace "
                "(likely a bad paste); expected a single fine-grained "
                "PAT starting with 'github_pat_' or a classic PAT "
                "starting with 'ghp_'"}
    if len(token) < 8 or len(token) > 400:
        return {"ok": False, "error": "token length looks wrong"}
    tmp = p.with_suffix(p.suffix + ".tmp")
    header = (
        "# arena-agent GitHub token (v4.50.0).\n"
        "# Read by arena.admin.update_github.github_token() when no\n"
        "# GITHUB_TOKEN / GH_TOKEN env var is set. Overwrite via the\n"
        "# Dashboard Settings tab or delete the file to clear.\n"
    )
    try:
        tmp.write_text(header + token + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # noqa: PTH101 - Windows silently ignores
        except Exception:
            pass
        os.replace(tmp, p)  # noqa: PTH105 - atomic on both POSIX + Windows
    except Exception as e:
        return {"ok": False, "error": f"failed to write token file: {e!r}"}
    return {"ok": True, "path": str(p), "source": "file"}


def clear_github_token() -> dict:
    """Remove <install_root>/.github_token. Does not touch env
    vars -- if an env var is set, the caller will keep seeing it.
    Called by /v1/admin/update/token-clear."""
    p = _token_file_path()
    if p is None:
        return {"ok": False, "error": "install root not resolvable"}
    if not p.exists():
        return {"ok": True, "removed": False, "path": str(p)}
    try:
        p.unlink()
    except Exception as e:
        return {"ok": False, "error": f"failed to remove: {e!r}"}
    return {"ok": True, "removed": True, "path": str(p)}


def http_get_json(url: str) -> Any:
    """Authenticated JSON GET. Raises urllib.error.HTTPError /
    URLError on network failure so callers can distinguish rate
    limit (403) from network trouble."""
    headers = {
        "User-Agent": _user_agent(),
        "Accept": "application/vnd.github+json",
    }
    tok = github_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # nosec B310 -- fixed api.github.com URL for release lookup  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
        return json.loads(resp.read().decode("utf-8"))


def pick_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer arena-agent-vX.Y.Z.zip; fall back to arena-agent.zip
    alias; last resort any *.zip."""
    zips = [a for a in assets if str(a.get("name", "")).endswith(".zip")]
    for a in zips:
        name = str(a.get("name", ""))
        if name.startswith("arena-agent-v") and name.endswith(".zip"):
            return a
    for a in zips:
        if str(a.get("name")) == "arena-agent.zip":
            return a
    return zips[0] if zips else None


def fetch_asset_size(asset_url: str) -> int | None:
    """HEAD an asset URL to learn its size without downloading.
    GitHub redirects `/releases/download/...` to a signed S3 URL that
    exposes Content-Length. urllib's default follower drops HEAD on
    30x, so we follow one redirect manually."""
    try:
        req = urllib.request.Request(
            asset_url, method="HEAD",
            headers={"User-Agent": _user_agent()})

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_a, **_k):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        try:
            resp = opener.open(req, timeout=_HTTP_TIMEOUT)
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location")
                if not loc:
                    return None
                req2 = urllib.request.Request(
                    loc, method="HEAD",
                    headers={"User-Agent": _user_agent()})
                resp2 = urllib.request.urlopen(req2, timeout=_HTTP_TIMEOUT)  # nosec B310 -- fixed api.github.com URL for release lookup  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
                cl = resp2.headers.get("Content-Length")
                return int(cl) if cl else None
            return None
    except Exception:
        return None


def fetch_changelog_section(repo: str, tag: str,
                            *, fallback_top_n: int = 3) -> str | None:
    """Pull the CHANGELOG.md section for `tag` via raw.githubusercontent.com.

    raw.githubusercontent.com is unauthenticated + not rate-limited
    (verified 2026-07). Tries `master` first, then `main`. Cap at 4 KB.

    Strategy:
      1. Look for `## v<version>` -- exact match.
      2. If not found (common when the release script forgot to
         prepend the new block), return the first `fallback_top_n`
         blocks with a "(showing latest N entries, exact block for
         v<version> not found)" preamble so the user still sees
         *something* useful in the Dashboard.
      3. If CHANGELOG.md doesn't exist at all, return None.

    Returns None on total failure -- release notes are best-effort.
    """
    version = tag.lstrip("vV").split("-")[0]
    exact_pattern = re.compile(
        r"^##\s+v?" + re.escape(version) + r"(?:[^\n]*)\n(.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    # A generic "any ## v..." pattern used by the fallback path.
    any_pattern = re.compile(
        r"^(##\s+v[^\n]*)\n(.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for branch in ("master", "main"):
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/CHANGELOG.md"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": _user_agent()})
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # nosec B310 -- fixed api.github.com URL for release lookup  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
                text = resp.read().decode("utf-8", "replace")
        except Exception:
            continue
        # Exact match path.
        m = exact_pattern.search(text)
        if m:
            return m.group(1).strip()[:4000]
        # Fallback: return the last N ## v-blocks so the Dashboard
        # isn't blank when the CHANGELOG hasn't been updated for the
        # latest tag yet. Prefixed with a note so the user knows it's
        # not an exact match.
        blocks = any_pattern.findall(text)
        if blocks:
            preamble = (
                f"_Exact block for v{version} not published in "
                "CHANGELOG.md yet -- showing the most recent "
                f"{min(fallback_top_n, len(blocks))} entries._\n\n"
            )
            picked = blocks[:fallback_top_n]
            joined = "\n\n".join(
                f"{header}\n{body.strip()}"
                for header, body in picked
            )
            return (preamble + joined)[:4000]
    return None


def resolve_latest_via_redirect(repo: str) -> str | None:
    """Read the tag from the /releases/latest 302 Location. Zero API
    quota cost. Returns None on failure."""
    url = f"https://github.com/{repo}/releases/latest"
    req = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": _user_agent()})

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_a, **_k):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(req, timeout=_HTTP_TIMEOUT)
        return None
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            return None
        location = e.headers.get("Location") or ""
        marker = "/releases/tag/"
        idx = location.find(marker)
        if idx < 0:
            return None
        return location[idx + len(marker):].split("?")[0].split("#")[0]
    except Exception:
        return None
