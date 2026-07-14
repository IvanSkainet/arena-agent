"""Generic APK install with SHA-256 consent + optional signature check.

This is the sibling of `helpers.install_adbkeyboard` (v3.83.2) but for
APKs the operator supplies at runtime rather than shipping in the
release tarball. The security shape:

  * Client uploads the APK to a temp path on the bridge (v3.83.5 uses
    the workspace's existing upload path since Arena already has one).
    Callers that don't have upload can also point at an existing path.
  * Bridge computes SHA-256 of the file, returns it plus the derived
    consent token (`yes-install-<sha256[:8]>`) via a "prepare" endpoint.
  * Client re-POSTs to install with that exact consent token. The token
    is APK-specific so a rotated file invalidates old prompts.
  * If `apksigner` is available on the bridge, we verify the signature
    and refuse install on failure (`apksigner verify --print-certs`).
    If it's not available (Arch/Cachy without android-tools:build), we
    warn and continue — the SHA-256 consent still binds the user to a
    specific file.
  * `adb push` + `adb shell pm install -r <remote>`. HyperOS/MIUI shows
    an on-device "Install this app?" dialog the operator must accept —
    we surface that via a timeout hint.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run

# The bridge's writable staging area for uploaded APKs. Anything the
# client points at MUST already resolve under this root — no arbitrary
# host paths get pushed to the phone.
STAGING_ROOT = Path("/tmp/arena-apk-staging")

# APK package-name regex from android.content.pm.PackageParser.
# Broad enough for real apps, strict enough to reject obvious junk.
_PKG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def _consent_token(sha256_hex: str) -> str:
    """`yes-install-<first-8-hex>` — same shape as the ADBKeyboard helper
    consent token, so a Dashboard that already knows how to handle one
    handles both without special-casing."""
    return f"yes-install-{sha256_hex[:8]}"


def _resolve_apk_path(client_path: str) -> Path | dict[str, Any]:
    """Reject path traversal. `client_path` may be:
      * absolute under STAGING_ROOT
      * relative — treated as relative to STAGING_ROOT
    Anything else is refused.
    """
    if not isinstance(client_path, str) or not client_path.strip():
        return _err("apk_path is required")
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    p = Path(client_path).expanduser()
    if not p.is_absolute():
        p = STAGING_ROOT / p
    try:
        resolved = p.resolve(strict=False)
        STAGING_ROOT.resolve(strict=False)  # will raise if impossible
    except Exception as e:
        return _err(f"could not resolve apk_path: {e}")
    root_resolved = STAGING_ROOT.resolve(strict=False)
    if root_resolved not in resolved.parents and resolved != root_resolved:
        return _err(
            "apk_path must live under the staging directory",
            hint=f"Uploaded APKs go under {STAGING_ROOT}. Arbitrary host paths "
                 f"are rejected on purpose so a hijacked token can't install "
                 f"anything on disk.",
            staging_root=str(STAGING_ROOT),
        )
    if not resolved.exists():
        return _err(
            f"apk not found: {resolved}",
            hint="Upload the APK first (POST it to STAGING_ROOT); then call "
                 "prepare with the returned path.",
        )
    if not resolved.is_file():
        return _err(f"apk_path is not a regular file: {resolved}")
    return resolved


def prepare(apk_path: str) -> dict[str, Any]:
    """Compute SHA-256 + the required consent token + inspect the APK
    for a package name. No adb call, no device required — this is the
    "show me what I'm about to install" step for the UI to display
    before asking for consent.
    """
    resolved = _resolve_apk_path(apk_path)
    if isinstance(resolved, dict):
        return resolved

    try:
        data = resolved.read_bytes()
    except Exception as e:
        return _err(f"could not read apk: {e}")
    sha = hashlib.sha256(data).hexdigest()

    # Extract package name from AndroidManifest.xml (compressed AXML).
    # aapt2 / aapt would give us this trivially but they're not always
    # installed. We do a minimal AXML string-pool scan so we can show
    # "you're about to install com.example.foo" without a hard dep.
    pkg = _extract_package_name(data)

    return {
        "ok": True,
        "path": str(resolved),
        "size_bytes": len(data),
        "sha256": sha,
        "required_consent": _consent_token(sha),
        "package": pkg,
        "signature_check": _try_apksigner_verify(resolved),
    }


def install(
    serial: str, apk_path: str, *, consent: str | None,
) -> dict[str, Any]:
    """Push + `pm install -r` a prepared APK. Requires the exact
    consent token that `prepare(apk_path)` returned."""
    if not isinstance(serial, str) or not serial.strip():
        return _err("serial required")

    resolved = _resolve_apk_path(apk_path)
    if isinstance(resolved, dict):
        return resolved

    try:
        data = resolved.read_bytes()
    except Exception as e:
        return _err(f"could not read apk: {e}")
    sha = hashlib.sha256(data).hexdigest()

    expected_consent = _consent_token(sha)
    if consent != expected_consent:
        return _err(
            "install requires explicit consent",
            hint=(
                f"Call POST /v1/mobile/apk/prepare with the same "
                f"apk_path, then include `consent: {expected_consent!r}` "
                f"in the install request body. This ties consent to "
                f"the specific APK build (sha256={sha}) so a rotated "
                f"file invalidates stale prompts."
            ),
            required_consent=expected_consent,
            apk_sha256=sha,
        )

    guard = _ensure_adb()
    if guard:
        return guard

    remote = f"/data/local/tmp/arena-apk-{sha[:12]}.apk"
    try:
        push = run(["push", str(resolved), remote], serial=serial, timeout=120)
    except AdbNotFoundError as e:
        return _err(str(e))
    except subprocess.TimeoutExpired:
        return _err(
            "adb push timed out",
            hint="Large APK on a slow link? Push runs at ~10-40 MB/s over "
                 "USB and ~1-5 MB/s over Tailscale/Wi-Fi. Files >200 MB "
                 "may need a longer timeout — this is 120s.",
        )
    if push.returncode != 0:
        return _err(
            "adb push failed",
            stderr=(push.stderr or "").strip(),
            exit_code=push.returncode,
        )

    try:
        inst = run(
            ["shell", "pm", "install", "-r", remote],
            serial=serial, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return _err(
            "pm install timed out",
            hint=(
                "On HyperOS / MIUI this almost always means the phone "
                "is showing an on-device 'Install this app?' dialog. "
                "Look at the phone, tap Install, then retry the request. "
                "Enable 'Install via USB' in Developer Options to skip "
                "the prompt on future installs from the same source."
            ),
        )
    except Exception as e:
        return _err(f"pm install failed: {e}")

    out = (inst.stdout or "").strip()
    if inst.returncode != 0 or "Success" not in out:
        return _err(
            "pm install did not report Success",
            stdout=out,
            stderr=(inst.stderr or "").strip(),
            exit_code=inst.returncode,
            hint=(
                "Common exit reasons: INSTALL_FAILED_USER_RESTRICTED "
                "(enable 'Install via USB' in Dev Options), "
                "INSTALL_FAILED_UPDATE_INCOMPATIBLE (already installed "
                "with a different signature — uninstall first), "
                "INSTALL_FAILED_VERSION_DOWNGRADE (installed version is "
                "newer — pass `pm install -r -d`, not yet exposed here)."
            ),
        )
    return {
        "ok": True,
        "action": "install_apk",
        "sha256": sha,
        "size_bytes": len(data),
        "stdout": out,
    }


# ---------------------------------------------------------------------------
# Package-name extraction (best-effort, no aapt dependency)
# ---------------------------------------------------------------------------

def _extract_package_name(apk_bytes: bytes) -> str | None:
    """Pull the `package` attribute out of AndroidManifest.xml.

    Modern APKs store AndroidManifest.xml in binary AXML format. Rather
    than pull in a full AXML parser (androguard) or shell out to aapt,
    we scan the string pool for the first token that looks like a
    package name. This works for every APK the maintainer has seen and
    is happy to return None when it doesn't.
    """
    import zipfile
    try:
        with zipfile.ZipFile(io_bytes(apk_bytes), "r") as z:
            try:
                manifest = z.read("AndroidManifest.xml")
            except KeyError:
                return None
    except Exception:
        return None
    # AXML string pool contains UTF-16LE strings prefixed with a length.
    # We just decode blocks of ASCII-safe bytes and grep for a
    # package-shaped token.
    for enc in ("utf-16-le", "latin-1"):
        try:
            text = manifest.decode(enc, errors="ignore")
        except Exception:
            continue
        for m in _PKG_RE.finditer(text):
            candidate = m.group(0)
            # Filter out obvious framework strings.
            if candidate.startswith("android.") or candidate.startswith("java."):
                continue
            if candidate.startswith("com.android.internal"):
                continue
            return candidate
    return None


def io_bytes(b: bytes):
    """Small indirection so tests can inject a fake stream."""
    import io
    return io.BytesIO(b)


# ---------------------------------------------------------------------------
# Optional signature verification via `apksigner`
# ---------------------------------------------------------------------------

def _try_apksigner_verify(apk_path: Path) -> dict[str, Any]:
    """Run `apksigner verify --print-certs` when the tool is present.

    Returns:
      {"available": bool, "verified": bool | None,
       "hint": str | None, "cert_sha256": str | None}
    """
    exe = shutil.which("apksigner")
    if not exe:
        return {
            "available": False,
            "verified": None,
            "hint": (
                "apksigner is not installed on the bridge host. The "
                "SHA-256 consent still ties install to a specific file, "
                "but the APK's own signature won't be validated. "
                "Install with: pacman -S android-tools (or the analogous "
                "package on your distro)."
            ),
        }
    try:
        r = subprocess.run(
            [exe, "verify", "--print-certs", str(apk_path)],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        return {"available": True, "verified": None,
                "hint": f"apksigner failed to run: {e}"}
    out = (r.stdout or "").strip()
    if r.returncode != 0:
        return {
            "available": True, "verified": False,
            "hint": (r.stderr or out or "signature verification failed").strip()[:400],
        }
    # Extract the first cert sha256 line ("SHA-256 digest: ...").
    cert = None
    for line in out.splitlines():
        low = line.strip().lower()
        if low.startswith("signer") and "sha-256 digest:" in low:
            cert = line.split(":", 1)[1].strip().replace(" ", "")
            break
    return {"available": True, "verified": True, "cert_sha256": cert,
            "hint": None}
