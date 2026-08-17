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
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# v4.169.1: both of these used to sit at the bottom of the file behind
# a lint suppression for E402, because auto_update_windows imported
# _REPLACE_TARGETS
# back from here -- a genuine cycle, documented by a test that hoisted
# the import and asserted the ImportError.
#
# Extracting the replace-target list into `update_targets` dissolved
# that cycle: both modules now import a third one instead of each
# other. The test correctly failed the moment the cycle disappeared and
# told us to hoist for real, which is this.
from arena.admin.auto_update_windows import _write_windows_installer
from arena.admin.deployment_provenance import (
    DEPLOYED_PROVENANCE,
    ProvenanceError,
    official_asset_authenticated as _official_asset_authenticated,
    prepare_install_provenance,
)
from arena.admin.deployment_tombstones import stage_release_tombstones
from arena.admin.update_github import (
    fetch_asset_size as _fetch_asset_size,
    fetch_changelog_section as _fetch_changelog_section,
    github_token as _github_token,
    http_get_json as _http_get_json,
    pick_asset as _pick_asset,
    resolve_latest_via_redirect as _resolve_latest_via_redirect,
)
from arena.admin.update_targets import (  # noqa: F401
    _NEVER_REPLACE,
    _REPLACE_TARGETS,
    _STATIC_REPLACE_TARGETS,
    replace_targets,
)
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


__all_helpers = [_write_windows_installer]  # keep import visible to linters


from arena.admin.auto_update_fetch import download_release  # noqa: E402


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

# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def consent_token(*, tag: str, sha256: str, asset_url: str = "") -> str:
    """`yes-update-<hex>`. Same shape as the APK install consent so
    operators recognise the pattern.

    v4.50.2: when ``sha256`` is the sentinel ``"UNVERIFIED"`` the
    consent still comes out as a stable per-tag string, but the
    caller must have explicitly opted out of SHA-256 verification.
    apply_update() emits a distinct audit trail in that case.

    v4.165.0 (bug #70): ``asset_url`` is now part of the token, and the
    unverified path *requires* it.

    The consent exists so an operator approves a specific thing before
    the bridge overwrites its own code. It covered the tag and the
    digest, but not where the bytes come from. On the verified path that
    is survivable -- a substituted URL serves different bytes, the digest
    check fails, the install aborts. On the **unverified** path nothing
    else is checked: the digest is the string ``"UNVERIFIED"``, and SSRF
    validation only blocks loopback and link-local, so any public HTTPS
    host is fair game. The operator approves "update to v4.164.0" and the
    approval fits a ZIP from anywhere.

    The token also used only the first 8 hex characters -- 32 bits.
    Consent is not a secret an attacker can brute-force offline (it is
    derived from values they already know), so the width was never the
    weak part; it is widened to 16 anyway because the cost is zero and a
    32-bit space invites accidental collisions in audit logs.
    """
    if sha256 == "UNVERIFIED" and not asset_url:
        # Fail closed. Without a digest, the URL is the ONLY thing tying
        # the approval to a specific artefact, so a caller that omits it
        # is asking for a token that authorises anything.
        raise ValueError(
            "asset_url is required for an unverified-install consent token; "
            "without a digest the URL is the only thing the operator is "
            "actually approving"
        )
    material = f"{tag}|{sha256}|{asset_url}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"yes-update-{digest[:16]}"

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


def _swap_unix(payload_root: Path, install_root: Path, *,
               backup_root: Path | None = None,
               provenance_path: Path | None = None) -> dict[str, Any]:
    """Atomically replace targets while retaining an identified rollback tree."""
    ts = int(time.time())
    swapped: list[str] = []
    backups: list[tuple[Path, Path]] = []
    created_backup_root = False
    try:
        if backup_root is not None:
            backup_root.mkdir(parents=True, exist_ok=False)
            created_backup_root = True
        names = list(replace_targets(payload_root))
        if provenance_path is not None:
            names.append(DEPLOYED_PROVENANCE)
        for name in names:
            src = provenance_path if name == DEPLOYED_PROVENANCE else payload_root / name
            dst = install_root / name
            if src is None or not src.exists():
                continue
            backup = (
                backup_root / name if backup_root is not None
                else install_root / f".{name}.old-{ts}"
            )
            if dst.exists():
                dst.rename(backup)
                backups.append((backup, dst))
            shutil.move(str(src), str(dst))
            swapped.append(name)
        backups.extend(stage_release_tombstones(
            install_root, backup_root=backup_root, timestamp=ts))
    except Exception as e:
        # Remove every newly moved target, including ones that had no prior
        # destination, then restore the retained old targets.
        for name in reversed(swapped):
            dst = install_root / name
            try:
                if dst.is_dir():
                    shutil.rmtree(dst, ignore_errors=True)
                else:
                    dst.unlink(missing_ok=True)
            except Exception:
                pass
        restore_ok = True
        for backup, dst in reversed(backups):
            try:
                backup.rename(dst)
            except Exception:
                restore_ok = False
        if created_backup_root and backup_root is not None and restore_ok:
            shutil.rmtree(backup_root, ignore_errors=True)
        return _err(f"swap failed: {e!r}",
                    swapped=swapped,
                    restored=restore_ok,
                    rollback_path=str(backup_root) if backup_root is not None else None,
                    rollback_retained=bool(backup_root and backup_root.exists()))
    # Ephemeral backups only protect the in-flight swap. Identified rollback
    # trees are retained under backups/deployments until explicit pruning.
    if backup_root is None:
        for backup, _dst in backups:
            try:
                if backup.is_dir():
                    shutil.rmtree(backup, ignore_errors=True)
                else:
                    backup.unlink(missing_ok=True)
            except Exception:
                pass
    return {
        "ok": True,
        "swapped": swapped,
        "rollback_path": str(backup_root) if backup_root is not None else None,
    }


def apply_update(*, asset_url: str, asset_name: str,
                 tag: str, expected_sha256: str | None = None,
                 consent: str,
                 restart: bool = True,
                 accept_no_verification: bool = False) -> dict[str, Any]:
    """Download + install + (optionally) restart. Never re-execs on
    Windows -- returns `restart_pending=True` so a supervisor (or the
    Dashboard) can bounce the service.

    v4.50.2: when ``accept_no_verification=True`` and no
    ``expected_sha256`` is supplied, the download proceeds with
    the SHA-256 recorded for audit but NOT compared to a
    published digest. The consent token switches to the
    ``UNVERIFIED`` sentinel so an operator who wants the safer
    path cannot accidentally reuse an old verified consent to
    trigger an unverified install. Meant for the Windows /
    no-token case where paying the GITHUB_TOKEN price is not
    reasonable and the operator explicitly accepts the risk.
    """
    if not asset_url or not asset_name or not tag:
        return _err("asset_url, asset_name and tag are required")
    expected = (expected_sha256 or "").split(":", 1)[-1].strip().lower()
    unverified = False
    if not expected:
        if not accept_no_verification:
            return _err(
                "expected_sha256 is required for safety",
                hint=(
                    "Either provide a token so GitHub returns a digest, "
                    "or resend the request with accept_no_verification=true "
                    "AND consent="
                    + consent_token(tag=tag, sha256="UNVERIFIED",
                                    asset_url=asset_url)
                ),
            )
        unverified = True
        expected = "UNVERIFIED"
    # v4.165.0 (bug #70): the source URL is part of the consent now. On
    # the unverified path it is the ONLY thing binding the approval to a
    # specific artefact, so a token minted for the official release no
    # longer authorises a ZIP fetched from somewhere else.
    want_consent = consent_token(tag=tag, sha256=expected, asset_url=asset_url)
    if (consent or "").strip() != want_consent:
        return _err("consent token missing or wrong",
                    hint=f"Pass consent={want_consent}")

    # For the verified path we forward expected_sha256 so download_release
    # bails on mismatch. For the unverified path we still record the
    # computed digest in the return value + audit trail but do not compare.
    dl = download_release(asset_url=asset_url, asset_name=asset_name,
                          expected_sha256=None if unverified else expected_sha256,
                          allow_unverified=unverified)
    if not dl.get("ok"):
        return dl
    zip_path = Path(dl["path"])
    staging = Path(dl["staging_dir"])
    extract_root = staging / "extracted"
    payload_root = _extract(zip_path, extract_root)
    install_root = _install_root()
    actual_sha256 = str(dl.get("sha256") or "")
    authenticated = (
        not unverified
        and _official_asset_authenticated(
            repo=_repo(), trusted_repo=DEFAULT_REPO, tag=tag,
            asset_url=asset_url, asset_name=asset_name, sha256=actual_sha256,
            fetch_json=_http_get_json,
        )
    )
    try:
        prepared = prepare_install_provenance(
            payload_root=payload_root,
            install_root=install_root,
            staging=staging,
            tag=tag,
            downloaded_sha256=actual_sha256,
            expected_sha256=None if unverified else expected,
            authenticated=authenticated,
        )
    except ProvenanceError as exc:
        return _err(f"release provenance verification failed: {exc}")
    deployed = prepared["deployed"]
    staged_provenance = prepared["staged"]
    backup_root = prepared["backup_root"]
    history_quarantine = prepared["history_quarantine"]

    if _WIN:
        marker = staging / "done.txt"
        script = _write_windows_installer(
            payload_root, install_root, marker,
            backup_root=backup_root,
            provenance_path=staged_provenance,
        )
        # v4.60.16: launch the mover via wscript+VBS wrapper instead of
        # subprocess.Popen(cmd, DETACHED_PROCESS). The naive Popen path
        # ended up sharing the parent's console because DETACHED_PROCESS
        # is silently downgraded when the parent already has a console;
        # when the parent (this bridge) died 1s later from os._exit(0),
        # the cmd.exe running the mover died with it, before the mover's
        # ``:wait`` loop even started. Symptom in .arena-update-apply.log:
        # only the ``mover-start`` line, never ``bridge exited``.
        # Windows Script Host (wscript.exe) is properly detached from any
        # console and survives parent exit. We drop a one-line .vbs
        # shim next to the mover .cmd that just Runs it with WindowStyle
        # hidden and NoWait, then spawn the .vbs.
        vbs_shim = script.with_suffix(".vbs")
        cmd_win = str(script).replace('"', '""')
        vbs_shim.write_bytes((
            'Set WshShell = CreateObject("WScript.Shell")\r\n'
            f'WshShell.Run "cmd /c ""{cmd_win}""", 0, False\r\n'
        ).encode("utf-8"))
        subprocess.Popen(
            ["wscript.exe", str(vbs_shim)],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return {
            "ok": True,
            "action": "update.apply",
            "platform": "windows",
            "installer_script": str(script),
            "install_root": str(install_root),
            "applied_version": tag.lstrip("vV"),
            "restart_pending": True,
            "verification": "unverified" if unverified else "sha256",
            "downloaded_sha256": dl.get("sha256"),
            "deployment": deployed,
            "rollback_path": str(backup_root) if backup_root is not None else None,
            "history_quarantine": history_quarantine,
            "hint": "The bridge will exit; a supervisor (systemd / nssm / "
                    "Windows service) must relaunch it.",
        }

    swap = _swap_unix(
        payload_root,
        install_root,
        backup_root=backup_root,
        provenance_path=staged_provenance,
    )
    if not swap.get("ok"):
        return swap
    result = {
        "ok": True,
        "action": "update.apply",
        "platform": platform.system().lower(),
        "verification": "unverified" if unverified else "sha256",
        "downloaded_sha256": dl.get("sha256"),
        "install_root": str(install_root),
        "swapped": swap["swapped"],
        "applied_version": tag.lstrip("vV"),
        "restart_pending": bool(restart),
        "sha256": dl["sha256"],
        "deployment": deployed,
        "rollback_path": swap.get("rollback_path"),
        "history_quarantine": history_quarantine,
    }
    return result


def restart_process(*, delay_sec: float = 0.5, force: bool = False,
                    install_root: Path | str | None = None,
                    relauncher_prepared: bool = False) -> dict[str, Any]:
    """Re-exported from :mod:`arena.admin.restart_process`.

    Kept as a thin forwarder because handlers, tests and the dashboard
    all import it from here; moving the implementation should not break
    a caller that has worked for a hundred releases.
    """
    from arena.admin import restart_process as _rp

    return _rp.restart_process(
        delay_sec=delay_sec,
        force=force,
        install_root=install_root,
        relauncher_prepared=relauncher_prepared,
    )
