"""Cross-platform auto-update for arena-agent (v3.85.0).

User-requested feature: check GitHub for a newer release, download the
zip, verify SHA-256 against the release asset digest, atomically
install into place, and restart the running bridge so the new code
takes over.

Design goals:

* **Cross-platform** (Windows / macOS / Linux). Windows needs an
  external mover script because you can't overwrite files owned by a
  running Python process; Unix can atomic-`mv` the new install
  directory into place and re-exec.
* **Consent gated.** Every install call needs a `consent` token
  computed from the release tag + sha256, exactly like the APK
  install flow in v3.83.5. Prevents accidental / adversarial
  auto-application.
* **Never touches config / data.** Only replaces the source tree
  under `arena/`, `dashboard/`, `docs/`, `scripts/`, `bin/`,
  `unified_bridge.py`, `pyproject.toml`, `README*`. Bridge home
  (tokens, audit log, tunnels config) is left alone.
* **Never runs sudo.** Whatever user is running the bridge is the
  user that must own the install directory.
* **Rolls back on failure.** The staged install writes to
  `<install>/.arena-update-staging/` and only swaps on success. A
  crashed download or a bad checksum never touches the running tree.
* **No network at import time.** The GitHub client only fires from
  the check/apply endpoints; import stays offline for CI.

Layout:

    check_updates()      -> {ok, current, latest, needs_update, ...}
    download_release()   -> {ok, staging_path, sha256}
    verify_sha256()      -> bool
    apply_update()       -> {ok, applied_version, restart_pending: bool}
    consent_token(...)   -> str        (same shape as apk_install)
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from arena.constants import VERSION as _CURRENT_VERSION


# GitHub org/repo that hosts the release. Overridable via env for
# testing / forks.
DEFAULT_REPO = "IvanSkainet/arena-agent"

# HTTP timeout for every GitHub API call. Deliberately short -- if
# GitHub is unreachable we want to fail the check quickly rather than
# stall a dashboard request.
_HTTP_TIMEOUT = 15

# User-Agent required by the GitHub API. We include the current
# version so telemetry-friendly forks can see the fleet mix.
_USER_AGENT = f"arena-agent-auto-update/{_CURRENT_VERSION}"

# Files/directories that get REPLACED wholesale on install. Everything
# else in the install root is left untouched (config, tokens, logs,
# bridge home).
_REPLACE_TARGETS = (
    "arena",
    "dashboard",
    "docs",
    "scripts",
    "bin",
    "unified_bridge.py",
    "pyproject.toml",
    "README.md",
    "README.ru.md",
    "CHANGELOG.md",
    "CHANGELOG.ru.md",
    "assets",
    "install.sh",
    "install.bat",
    "uninstall.sh",
    "uninstall.bat",
)


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _repo() -> str:
    return os.environ.get("ARENA_UPDATE_REPO", DEFAULT_REPO).strip()


def _install_root() -> Path:
    """Directory that gets replaced. We derive it from where the
    package sits so a `pip install`-style layout would still work."""
    override = os.environ.get("ARENA_UPDATE_ROOT")
    if override:
        return Path(override).resolve()
    # arena/admin/auto_update.py -> arena/admin -> arena -> repo root.
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Version parsing + comparison
# ---------------------------------------------------------------------------

def parse_version(tag: str) -> tuple[int, ...]:
    """`v3.84.7` / `3.84.7` / `v3.84.7-rc1` -> `(3, 84, 7)`.

    Non-numeric suffixes are dropped; ordering follows plain integer
    tuple comparison which is enough for the semver-lite scheme this
    project actually uses.
    """
    s = (tag or "").strip().lstrip("vV")
    parts: list[int] = []
    for chunk in s.split("."):
        buf = ""
        for ch in chunk:
            if ch.isdigit():
                buf += ch
            else:
                break
        if not buf:
            break
        parts.append(int(buf))
    return tuple(parts) if parts else (0,)


def is_newer(candidate: str, baseline: str) -> bool:
    """Strictly greater than the baseline."""
    return parse_version(candidate) > parse_version(baseline)


# ---------------------------------------------------------------------------
# GitHub helpers (moved to arena.admin.update_github in v3.86.2 so this
# file stays under the 600-line per-module cap). Backwards-compatible
# private aliases are kept because existing tests + external callers
# monkeypatch them by name.
# ---------------------------------------------------------------------------

from arena.admin.update_github import (
    github_token as _github_token,
    http_get_json as _http_get_json,
    pick_asset as _pick_asset,
    fetch_asset_size as _fetch_asset_size,
    fetch_changelog_section as _fetch_changelog_section,
    resolve_latest_via_redirect as _resolve_latest_via_redirect,
)


def check_updates(*, current_version: str | None = None) -> dict[str, Any]:
    """Ask GitHub what the latest release is.

    v3.85.3: two-tier strategy so anonymous bridges don't 403:

      1. Try the redirect on `github.com/<repo>/releases/latest`.
         This costs zero API quota. We use it to learn the tag name
         and to construct predictable asset URLs.
      2. Only call the JSON API if we have a token OR the redirect
         path failed to yield a tag. When the API answers 403 we
         gracefully fall through to a redirect-only response.

    Never raises. On total failure returns `{ok: False, error: ...}`
    so the HTTP handler can surface the real reason.
    """
    baseline = current_version or _CURRENT_VERSION
    repo = _repo()
    token = _github_token()

    # Fast path: try the JSON API only if we have a token (no rate
    # limit worry) OR if it's the first thing we know how to do.
    api_error = None
    api_data: dict[str, Any] | None = None
    if token:
        try:
            data = _http_get_json(
                f"https://api.github.com/repos/{repo}/releases/latest")
            if isinstance(data, dict):
                api_data = data
        except urllib.error.HTTPError as e:
            api_error = f"GitHub API returned HTTP {e.code}"
        except urllib.error.URLError as e:
            api_error = f"GitHub API unreachable: {e.reason}"
        except Exception as e:
            api_error = f"GitHub API failure: {e!r}"

    if api_data is not None:
        tag = str(api_data.get("tag_name") or "")
        assets = api_data.get("assets") or []
        asset = _pick_asset(assets)
        if asset is None:
            return _err(f"release {tag} has no downloadable zip",
                        repo=repo, tag=tag)
        return {
            "ok": True,
            "repo": repo,
            "current": baseline,
            "latest": tag.lstrip("vV"),
            "latest_tag": tag,
            "needs_update": is_newer(tag, baseline),
            "asset_name": asset.get("name"),
            "asset_url": asset.get("browser_download_url"),
            "asset_size_bytes": asset.get("size"),
            "asset_digest": asset.get("digest"),
            "published_at": api_data.get("published_at"),
            "release_url": api_data.get("html_url"),
            "body": (api_data.get("body") or "")[:2000],
            "source": "api",
        }

    # Redirect fallback (no token, or API refused).
    tag = _resolve_latest_via_redirect(repo)
    if not tag:
        return _err(
            api_error or "could not resolve latest release "
            "(neither the API nor the /releases/latest redirect responded)",
            repo=repo,
            hint=("Set GITHUB_TOKEN or GH_TOKEN in the bridge's environment "
                  "to bypass the 60/hour anonymous rate limit."),
        )
    # Build the canonical asset URL. Release zip is always
    # arena-agent-<tag>.zip AND a stable alias arena-agent.zip;
    # both live at /releases/download/<tag>/<name>.
    asset_name_versioned = f"arena-agent-{tag}.zip"
    asset_name_alias = "arena-agent.zip"
    asset_url = f"https://github.com/{repo}/releases/download/{tag}/{asset_name_versioned}"
    # Best-effort enrichment: neither call is required for install
    # (the redirect path can't verify SHA-256 anyway), but both make
    # the Dashboard feel like a real product instead of a JSON dump.
    asset_size = _fetch_asset_size(asset_url)
    body = _fetch_changelog_section(repo, tag) or ""
    return {
        "ok": True,
        "repo": repo,
        "current": baseline,
        "latest": tag.lstrip("vV"),
        "latest_tag": tag,
        "needs_update": is_newer(tag, baseline),
        "asset_name": asset_name_versioned,
        "asset_url": asset_url,
        "asset_size_bytes": asset_size,
        "asset_digest": None,      # unknown without API
        "published_at": None,
        "release_url": f"https://github.com/{repo}/releases/tag/{tag}",
        "body": body,
        "source": "redirect",
        "asset_alias_name": asset_name_alias,
        "hint": (
            api_error and ("API path returned: " + api_error) or None
        ),
    }


# ---------------------------------------------------------------------------
# Download + verify
# ---------------------------------------------------------------------------

def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_release(*, asset_url: str, asset_name: str,
                     expected_sha256: str | None = None,
                     dest_dir: Path | str | None = None) -> dict[str, Any]:
    """Download a release zip to `dest_dir` (default: a fresh temp dir)
    and compute its SHA-256. Optionally verifies against
    `expected_sha256` (accepts `sha256:...` prefix as GitHub returns)."""
    if not asset_url or not asset_name:
        return _err("asset_url and asset_name are required")
    dest = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="arena-update-"))
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / asset_name
    try:
        # v4.43.0: SSRF + size-cap defence for the release
        # download. asset_url is fed from the /v1/update  # nosec B310 -- inspected -- fixed / SSRF-guarded URL
        # endpoint which already restricts sources, but a
        # compromised upstream (or a badly-configured
        # allowlist) shouldn't be able to stream unlimited
        # bytes into the operator's disk. 512 MiB is well over
        # a real release (~3 MB); an archive that big is
        # already something we don't want to install.
        from arena.security_ssrf import _validate_url
        ssrf_err = _validate_url(asset_url)
        if ssrf_err:
            return _err(f"asset_url rejected: {ssrf_err}",
                        asset_url=asset_url)
        req = urllib.request.Request(asset_url, headers={"User-Agent": _USER_AGENT})
        _MAX = 512 * 1024 * 1024
        with urllib.request.urlopen(req, timeout=60) as resp, zip_path.open("wb") as out:  # nosec B310 -- SSRF-validated above; scheme forced to http/https by _validate_url
            written = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX:
                    return _err("release zip exceeded 512 MiB size cap",
                                asset_url=asset_url)
                out.write(chunk)
    except Exception as e:
        return _err(f"download failed: {e!r}", asset_url=asset_url)

    got = _sha256_of(zip_path)
    if expected_sha256:
        want = expected_sha256.split(":", 1)[-1].strip().lower()
        if want and want != got:
            return _err("sha256 mismatch after download",
                        expected=want, got=got, path=str(zip_path))
    return {
        "ok": True,
        "path": str(zip_path),
        "sha256": got,
        "size_bytes": zip_path.stat().st_size,
        "staging_dir": str(dest),
    }


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def consent_token(*, tag: str, sha256: str) -> str:
    """`yes-update-<first-8-hex-of-tag+sha>`. Same shape as the APK
    install consent so operators recognise the pattern."""
    digest = hashlib.sha256(f"{tag}|{sha256}".encode("utf-8")).hexdigest()
    return f"yes-update-{digest[:8]}"


# ---------------------------------------------------------------------------
# Install (cross-platform)
# ---------------------------------------------------------------------------

_WIN = platform.system().lower() == "windows"


def _extract(zip_path: Path, dest: Path) -> Path:
    """Extract the zip and return the top-level directory inside it
    (release zips wrap everything in `arena-agent/`).

    v4.42.2: routed through ``arena.files.safe_extract.safe_extract_zip``
    which rejects path-traversal / symlink / zip-bomb archives
    before writing any byte. The auto-update flow downloads the
    zip from a GitHub release URL that has already passed a
    signature-ish check (via the update endpoint's URL allowlist),
    but relying on ``ZipFile.extractall`` alone means one
    compromise upstream would turn every arena bridge into a
    remote code execution vector. Belt+suspenders.
    """
    from arena.files.safe_extract import safe_extract_zip
    dest.mkdir(parents=True, exist_ok=True)
    safe_extract_zip(zip_path, dest)
    # Find the single top-level directory.
    entries = [p for p in dest.iterdir() if p.is_dir()]
    if len(entries) == 1:
        return entries[0]
    # Zip didn't wrap -- treat dest as the payload root.
    return dest


def _swap_unix(payload_root: Path, install_root: Path) -> dict[str, Any]:
    """POSIX swap: for each replace-target, atomically `mv` the
    payload copy over the installed copy (with a `.old-<ts>` backup
    so we can roll back if the caller's chown or restart fails)."""
    ts = int(time.time())
    swapped: list[str] = []
    backups: list[tuple[Path, Path]] = []
    try:
        for name in _REPLACE_TARGETS:
            src = payload_root / name
            dst = install_root / name
            if not src.exists():
                continue
            backup = install_root / f".{name}.old-{ts}"
            if dst.exists():
                dst.rename(backup)
                backups.append((backup, dst))
            shutil.move(str(src), str(dst))
            swapped.append(name)
    except Exception as e:
        # Roll back any moves we already did.
        for backup, dst in backups:
            try:
                if dst.exists():
                    shutil.rmtree(dst, ignore_errors=True) if dst.is_dir() else dst.unlink()
                backup.rename(dst)
            except Exception:
                pass
        return _err(f"swap failed: {e!r}", swapped=swapped)
    # Delete backups asynchronously so a slow-mounted filesystem
    # doesn't stall the restart.
    for backup, _dst in backups:
        try:
            if backup.is_dir():
                shutil.rmtree(backup, ignore_errors=True)
            else:
                backup.unlink(missing_ok=True)
        except Exception:
            pass
    return {"ok": True, "swapped": swapped}


def _write_windows_installer(payload_root: Path, install_root: Path,
                             done_marker: Path) -> Path:
    """Windows can't overwrite files that a running Python process has
    open. We write a .cmd script that waits for our PID to exit, then
    robocopies the payload over the install root, then touches the
    done marker so a supervisor can restart us.
    """
    script = install_root / ".arena-update-apply.cmd"
    pid = os.getpid()
    src = payload_root.as_posix().replace("/", "\\")
    dst = install_root.as_posix().replace("/", "\\")
    lines = [
        "@echo off",
        f":wait",
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >NUL',
        "if not errorlevel 1 (",
        "  timeout /t 1 /nobreak >NUL",
        "  goto wait",
        ")",
    ]
    for name in _REPLACE_TARGETS:
        s = f"{src}\\{name}"
        d = f"{dst}\\{name}"
        # /MIR mirrors a directory; for a plain file we do a copy /Y.
        lines.append(
            f'if exist "{s}\\*" ( robocopy "{s}" "{d}" /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 ) '
            f'else ( if exist "{s}" copy /Y "{s}" "{d}" >NUL )'
        )
    lines.append(f'echo done > "{done_marker.as_posix().replace("/", chr(92))}"')
    script.write_text("\r\n".join(lines), encoding="utf-8")
    return script


def apply_update(*, asset_url: str, asset_name: str,
                 tag: str, expected_sha256: str | None = None,
                 consent: str,
                 restart: bool = True) -> dict[str, Any]:
    """Download + install + (optionally) restart. Never re-execs on
    Windows -- returns `restart_pending=True` so a supervisor (or the
    Dashboard) can bounce the service.
    """
    if not asset_url or not asset_name or not tag:
        return _err("asset_url, asset_name and tag are required")
    expected = (expected_sha256 or "").split(":", 1)[-1].strip().lower()
    if not expected:
        return _err("expected_sha256 is required for safety")
    want_consent = consent_token(tag=tag, sha256=expected)
    if (consent or "").strip() != want_consent:
        return _err("consent token missing or wrong",
                    hint=f"Pass consent={want_consent}")

    dl = download_release(asset_url=asset_url, asset_name=asset_name,
                          expected_sha256=expected_sha256)
    if not dl.get("ok"):
        return dl
    zip_path = Path(dl["path"])
    staging = Path(dl["staging_dir"])
    extract_root = staging / "extracted"
    payload_root = _extract(zip_path, extract_root)
    install_root = _install_root()

    if _WIN:
        marker = staging / "done.txt"
        script = _write_windows_installer(payload_root, install_root, marker)
        # Launch the mover DETACHED so it survives our exit.
        subprocess.Popen(
            ["cmd", "/c", str(script)],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return {
            "ok": True,
            "action": "update.apply",
            "platform": "windows",
            "installer_script": str(script),
            "install_root": str(install_root),
            "applied_version": tag.lstrip("vV"),
            "restart_pending": True,
            "hint": "The bridge will exit; a supervisor (systemd / nssm / "
                    "Windows service) must relaunch it.",
        }

    swap = _swap_unix(payload_root, install_root)
    if not swap.get("ok"):
        return swap
    result = {
        "ok": True,
        "action": "update.apply",
        "platform": platform.system().lower(),
        "install_root": str(install_root),
        "swapped": swap["swapped"],
        "applied_version": tag.lstrip("vV"),
        "restart_pending": bool(restart),
        "sha256": dl["sha256"],
    }
    return result


def restart_process(*, delay_sec: float = 0.5) -> dict[str, Any]:
    """Best-effort restart of the current Python process.

    On Unix we re-exec into `sys.argv`; the systemd unit picks it up
    as a clean restart. On Windows we just return -- the caller
    (dashboard, service supervisor) must relaunch us.
    """
    if _WIN:
        return {"ok": True, "restart": "pending",
                "hint": "Windows service supervisor must relaunch bridge."}
    # Give the HTTP handler a moment to flush its response before we
    # replace ourselves.
    import threading

    def _do_restart():
        time.sleep(max(0.05, delay_sec))
        try:
            os.execv(sys.executable, [sys.executable, *sys.argv])
        except Exception:
            os._exit(0)

    threading.Thread(target=_do_restart, daemon=True).start()
    return {"ok": True, "restart": "scheduled",
            "delay_sec": delay_sec, "argv": sys.argv[:1]}
