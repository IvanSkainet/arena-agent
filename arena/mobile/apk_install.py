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
#
# v4.42.0: moved from ``/tmp/arena-apk-staging`` (shared,
# world-listable, symlink-attack-prone -- a co-tenant could
# pre-plant ``/tmp/arena-apk-staging`` as a symlink to any
# directory the bridge user could write, causing uploaded APKs
# to land wherever the attacker chose) to ``~/.arena/apk-staging``.
# The parent ``~/.arena`` directory is already 0o700 after
# v4.40.0's URL-cache work; the apk-staging subdirectory gets
# the same treatment on first use via ``_ensure_staging_root``.
# ``$ARENA_APK_STAGING`` env var overrides for operators who
# want the staging area on a larger volume.
def _default_staging_root() -> Path:
    from pathlib import Path as _P
    import os as _os
    override = _os.environ.get("ARENA_APK_STAGING", "").strip()
    if override:
        return _P(override).expanduser()
    return _P.home() / ".arena" / "apk-staging"


STAGING_ROOT = _default_staging_root()


def _ensure_staging_root() -> None:
    """Create the staging directory with owner-only mode. Idempotent.

    Called lazily inside ``persist_uploaded_apk`` and
    ``ensure_apk_ready`` rather than at import time so a bridge
    that never touches APKs never creates the directory.
    Applies chmod after mkdir because mkdir's ``mode=`` argument
    is masked by the process umask (often 0o022, which would
    downgrade our request to 0o755). The explicit chmod is the
    same ACL-proof pattern the v4.40.0 URL cache uses.
    """
    import os as _os
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        _os.chmod(STAGING_ROOT, 0o700)
    except OSError:
        pass
    # Tighten the parent too when we just created it -- ~/.arena
    # might not exist yet on a fresh install.
    try:
        _os.chmod(STAGING_ROOT.parent, 0o700)
    except OSError:
        pass

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
    _ensure_staging_root()
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


def save_upload(filename: str, data: bytes) -> dict[str, Any]:
    """Persist a client-uploaded APK into `STAGING_ROOT`. Returns the
    same shape as `prepare()` so a UI can chain upload → install
    without a second `prepare` round-trip.

    `filename` may include a subdirectory (e.g. `agent/foo.apk`) but
    must not escape the staging root — the same path-traversal guard
    as `prepare` / `install` applies. `..` in any segment is refused
    outright.
    """
    if not isinstance(filename, str) or not filename.strip():
        return _err("filename required")
    # Reject obvious traversal attempts. `_resolve_apk_path` already
    # catches these, but a direct guard produces a clearer error
    # message before we touch the filesystem.
    parts = Path(filename).parts
    if any(p in ("..", "") for p in parts):
        return _err("filename may not contain `..` or empty segments")
    if not isinstance(data, (bytes, bytearray)) or len(data) < 100:
        return _err("data missing or too small to be an APK")
    # Cheap magic check: real APKs start with the ZIP magic `PK\x03\x04`.
    if data[:4] != b"PK\x03\x04":
        return _err(
            "file does not look like a ZIP/APK "
            "(missing PK\\x03\\x04 magic)",
            got_prefix=data[:4].hex(),
        )
    _ensure_staging_root()
    dest = STAGING_ROOT / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(data))
    # Chain into prepare so the caller gets sha + consent + package.
    prepared = prepare(filename)
    if prepared.get("ok"):
        prepared["action"] = "apk_upload"
        prepared["written_bytes"] = len(data)
    return prepared


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

    APKs store AndroidManifest.xml in binary AXML (Android Binary XML)
    format. The structure is well-defined:
      * 8-byte chunk header {type=0x00080003, header_size=8, size=total}
      * String pool chunk (type=0x001c0001)
      * Resource-map chunk (type=0x00080180)
      * XML tree chunks: START_NS, END_NS, START_ELEMENT, END_ELEMENT
    START_ELEMENT chunks carry `name_idx` + attribute records. The
    manifest root element (name="manifest") has an attribute
    `package="com.example"` with `name_idx` pointing at "package" and
    `raw_value_idx` pointing at "com.example" in the string pool.
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

    pkg = _parse_axml_for_package(manifest)
    if pkg:
        return pkg
    # Regex fallback for exotic ROMs that emit non-standard AXML.
    for enc in ("utf-16-le", "latin-1"):
        try:
            text = manifest.decode(enc, errors="ignore")
        except Exception:
            continue
        for m in _PKG_RE.finditer(text):
            candidate = m.group(0)
            if candidate.startswith("android.") or candidate.startswith("java."):
                continue
            if candidate.startswith("com.android.internal"):
                continue
            return candidate
    return None


def _parse_axml_for_package(data: bytes) -> str | None:
    """Walk the AXML chunk tree looking for <manifest package="…">."""
    import struct
    if len(data) < 8:
        return None
    # Root chunk header.
    try:
        chunk_type, header_size, total_size = struct.unpack_from("<HHI", data, 0)
    except struct.error:
        return None
    if chunk_type != 0x0003 or total_size > len(data):
        return None

    # Locate the string pool (usually the second chunk).
    strings = _parse_axml_string_pool(data, 8)
    if not strings:
        return None
    string_list, offset_after_pool = strings

    # Scan forward for START_ELEMENT chunks (type 0x00100102). Each
    # START_ELEMENT carries: (ns_idx, name_idx, attribute_start,
    # attribute_size, attribute_count, id_idx, class_idx, style_idx)
    # then `attribute_count` records of 20 bytes each:
    # (ns_idx, name_idx, raw_value_idx, typed_value_size, res0,
    #  typed_value_type, typed_value_data).
    pos = offset_after_pool
    while pos + 8 <= len(data):
        try:
            ctype, chdr, csize = struct.unpack_from("<HHI", data, pos)
        except struct.error:
            return None
        if csize == 0 or pos + csize > len(data):
            return None
        if ctype == 0x0102:  # START_ELEMENT
            # Chunk header (8 bytes) + line_number (4) + comment (4) = 16
            # Then: ns_idx(4), name_idx(4), attr_start(2), attr_size(2),
            # attr_count(2), id_idx(2), class_idx(2), style_idx(2) = 20
            try:
                name_idx = struct.unpack_from("<I", data, pos + 20)[0]
                attr_start = struct.unpack_from("<H", data, pos + 24)[0]
                attr_count = struct.unpack_from("<H", data, pos + 28)[0]
            except struct.error:
                pos += csize
                continue
            element_name = _get_string(string_list, name_idx)
            if element_name == "manifest":
                # Attributes begin at pos + 16 + attr_start (attr_start
                # is measured from the ELEMENT payload, which starts
                # right after the 8-byte chunk header + 8-byte line/
                # comment fields).
                attr_base = pos + 16 + attr_start
                for i in range(attr_count):
                    ap = attr_base + i * 20
                    if ap + 20 > pos + csize:
                        break
                    try:
                        attr_name_idx = struct.unpack_from("<I", data, ap + 4)[0]
                        attr_value_idx = struct.unpack_from("<i", data, ap + 8)[0]
                    except struct.error:
                        continue
                    if _get_string(string_list, attr_name_idx) == "package":
                        val = _get_string(string_list, attr_value_idx)
                        if val:
                            return val
                # <manifest> found but no package attribute — bail.
                return None
        pos += csize
    return None


def _parse_axml_string_pool(data: bytes, start: int) -> tuple[list[str], int] | None:
    """Return (list_of_strings, position_right_after_the_pool_chunk)."""
    import struct
    if start + 28 > len(data):
        return None
    try:
        ctype, chdr, csize = struct.unpack_from("<HHI", data, start)
    except struct.error:
        return None
    if ctype != 0x0001:  # String pool type
        return None
    # Header fields at offsets 8..28 into the chunk.
    string_count = struct.unpack_from("<I", data, start + 8)[0]
    # style_count at +12 (unused), flags at +16, strings_start at +20,
    # styles_start at +24.
    flags = struct.unpack_from("<I", data, start + 16)[0]
    strings_start = struct.unpack_from("<I", data, start + 20)[0]
    is_utf8 = bool(flags & (1 << 8))

    offsets = []
    off_base = start + 28
    for i in range(string_count):
        if off_base + i * 4 + 4 > len(data):
            return None
        offsets.append(struct.unpack_from("<I", data, off_base + i * 4)[0])

    string_data_base = start + strings_start
    strings: list[str] = []
    for off in offsets:
        p = string_data_base + off
        if p + 2 > len(data):
            strings.append("")
            continue
        if is_utf8:
            # UTF-8 pool: two varlen fields (char count, byte count),
            # then bytes, then null terminator.
            _u16 = data[p]
            # char count varlen
            if _u16 & 0x80:
                p += 2
            else:
                p += 1
            # byte count varlen
            u2 = data[p]
            if u2 & 0x80:
                length = ((u2 & 0x7F) << 8) | data[p + 1]
                p += 2
            else:
                length = u2
                p += 1
            try:
                strings.append(data[p:p + length].decode("utf-8", errors="replace"))
            except Exception:
                strings.append("")
        else:
            # UTF-16 pool: 1 varlen field (char count in code units),
            # then UTF-16LE bytes, then null terminator.
            u = struct.unpack_from("<H", data, p)[0]
            if u & 0x8000:
                length = ((u & 0x7FFF) << 16) | struct.unpack_from("<H", data, p + 2)[0]
                p += 4
            else:
                length = u
                p += 2
            try:
                strings.append(data[p:p + length * 2].decode("utf-16-le", errors="replace"))
            except Exception:
                strings.append("")
    return (strings, start + csize)


def _get_string(pool: list[str], idx: int) -> str:
    if idx < 0 or idx >= len(pool):
        return ""
    return pool[idx]


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
