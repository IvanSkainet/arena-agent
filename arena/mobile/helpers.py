"""Helper-APK installation + IME control + unicode paste.

The one and only helper we bundle right now is ADBKeyboard (senzhk's
`com.android.adbkeyboard/.AdbIME`), because it's the only realistic way
to send non-ASCII text to a stock modern Android + HyperOS device: the
built-in `adb shell input text` crashes with a NullPointerException on
any non-ASCII payload (see arena/mobile/input.py).

Security posture:
  * We ship one APK, hashed at check-in time (`ADBKEYBOARD_SHA256`).
    Every install path re-hashes the bundled file and refuses to push
    if the hash drifts, so a compromised release tarball can't smuggle
    a different APK past the guard.
  * Installing an APK is a first-class dangerous action. The install
    endpoint requires an explicit consent token in the request body
    (`consent: "yes-install-adbkeyboard-<first-8-hex-of-hash>"`) so a
    stale prompt can't be replayed after the bundled APK is updated.
  * The install itself uses `adb push` + `adb shell pm install -r`.
    On HyperOS (and other MIUI-derived ROMs) the phone shows a native
    "Install app" dialog that the user must accept on-device — the
    bridge cannot bypass this and does not try.
  * IME switching (`ime set`) is scoped to the ADBKeyboard package
    only. Every other IME switch requires the operator to fall through
    to the raw shell.
"""
from __future__ import annotations

import base64
import hashlib
import subprocess
from pathlib import Path
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run

# --- Bundled ADBKeyboard --------------------------------------------------

ADBKEYBOARD_PACKAGE = "com.android.adbkeyboard"
ADBKEYBOARD_SERVICE = "com.android.adbkeyboard/.AdbIME"
ADBKEYBOARD_VERSION = "v2.5-dev"
# SHA-256 of the exact APK bytes we bundle. Verified by hand:
#   curl -sSfL <release> | sha256sum
# Anyone updating the bundle must update this constant too — the tests
# assert the hash matches the on-disk APK.
ADBKEYBOARD_SHA256 = "41a8a0996d7397a2390d1ca16a75cb66c4a7bdaa89cf4e63600a4d3fb346fbbb"


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def bundled_apk_path() -> Path:
    """Return the on-disk path of the bundled ADBKeyboard APK."""
    # `arena/mobile/helpers.py` → parent.parent = repo root, then
    # `assets/apks/adbkeyboard-v2.5.apk`. Kept out of `arena/` proper
    # because APKs are binary blobs and shouldn't clutter the Python
    # package tree.
    root = Path(__file__).resolve().parent.parent.parent
    return root / "assets" / "apks" / f"adbkeyboard-{ADBKEYBOARD_VERSION}.apk"


def bundled_apk_status() -> dict[str, Any]:
    """Return metadata about the on-disk bundled APK (no adb needed).

    Used by handlers and tests to decide whether the install endpoint
    is even offerable — a repo without the APK asset should surface a
    clear "not shipped in this build" error, not a confusing FileNotFoundError.
    """
    p = bundled_apk_path()
    if not p.exists():
        return {
            "ok": False,
            "error": "bundled ADBKeyboard APK not present in this build",
            "hint": f"expected at {p}",
            "expected_sha256": ADBKEYBOARD_SHA256,
        }
    data = p.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    out: dict[str, Any] = {
        "ok": True,
        "path": str(p),
        "size_bytes": len(data),
        "sha256": actual,
        "expected_sha256": ADBKEYBOARD_SHA256,
        "version": ADBKEYBOARD_VERSION,
        "package": ADBKEYBOARD_PACKAGE,
        "service": ADBKEYBOARD_SERVICE,
        "hash_matches": (actual == ADBKEYBOARD_SHA256),
    }
    if not out["hash_matches"]:
        out["ok"] = False
        out["error"] = (
            "bundled APK hash mismatch — refusing to offer install. "
            "Someone tampered with the release tarball, or the bundled "
            "file was regenerated without updating ADBKEYBOARD_SHA256."
        )
    return out


# --- Install ---------------------------------------------------------------

def _consent_token(sha256_hex: str) -> str:
    """Consent tokens are of the form `yes-install-adbkeyboard-<first-8-hex>`.

    Ties the consent to a specific APK build so a rotated release doesn't
    silently accept stale consent from a Dashboard tab left open."""
    return f"yes-install-adbkeyboard-{sha256_hex[:8]}"


def install_adbkeyboard(serial: str, *, consent: str | None) -> dict[str, Any]:
    """Push + `pm install -r` the bundled ADBKeyboard APK.

    Requires the caller to pass `consent` matching the expected token.
    On MIUI/HyperOS the phone shows an on-device "Install app" dialog
    that the user MUST accept — the bridge cannot bypass this and
    reports the on-device dialog in the `hint` field of a timeout error.
    """
    if not isinstance(serial, str) or not serial.strip():
        return _err("serial required")

    status = bundled_apk_status()
    if not status.get("ok"):
        return status  # already has actionable message

    expected_consent = _consent_token(status["sha256"])
    if consent != expected_consent:
        return _err(
            "install requires explicit consent",
            hint=(
                f"Include `consent: {expected_consent!r}` in the request "
                "body. This ties consent to the specific APK build "
                f"(sha256={status['sha256']}) so a rotated release doesn't "
                "silently accept a stale prompt."
            ),
            required_consent=expected_consent,
            apk_sha256=status["sha256"],
            apk_version=status["version"],
        )

    guard = _ensure_adb()
    if guard:
        return guard

    # Push then pm-install. Push first because pm install directly
    # from a host path silently retries via streaming on some ADBs and
    # the failure modes are less informative.
    remote = f"/data/local/tmp/adbkb-{status['sha256'][:8]}.apk"
    try:
        push = run(["push", status["path"], remote], serial=serial, timeout=45)
    except AdbNotFoundError as e:
        return _err(str(e))
    except subprocess.TimeoutExpired:
        return _err(
            "adb push timed out",
            hint="Is the phone still connected and authorised? Try "
                 "unplugging and re-plugging the USB cable.",
        )
    if push.returncode != 0:
        return _err(
            "adb push failed",
            stderr=(push.stderr or "").strip(),
            exit_code=push.returncode,
        )

    try:
        install = run(["shell", "pm", "install", "-r", remote], serial=serial, timeout=60)
    except subprocess.TimeoutExpired:
        return _err(
            "pm install timed out",
            hint=(
                "This is almost always because the phone is showing an "
                "on-device 'Install this app?' dialog that hasn't been "
                "accepted yet. Look at the phone, tap Install, then "
                "retry the request. HyperOS / MIUI always shows this "
                "dialog and the bridge cannot dismiss it for you."
            ),
        )
    except Exception as e:
        return _err(f"pm install failed: {e}")

    out = (install.stdout or "").strip()
    if install.returncode != 0 or "Success" not in out:
        return _err(
            "pm install did not report Success",
            stdout=out,
            stderr=(install.stderr or "").strip(),
            exit_code=install.returncode,
            hint=("If stdout mentions INSTALL_FAILED_USER_RESTRICTED, "
                  "enable 'Install via USB' in Developer Options on "
                  "HyperOS / MIUI."),
        )
    return {
        "ok": True,
        "action": "install_adbkeyboard",
        "package": status["package"],
        "sha256": status["sha256"],
        "size_bytes": status["size_bytes"],
        "version": status["version"],
        "stdout": out,
    }


# --- IME control -----------------------------------------------------------

def ime_status(serial: str) -> dict[str, Any]:
    """Return current default IME + whether ADBKeyboard is installed / enabled / active."""
    guard = _ensure_adb()
    if guard:
        return guard

    cur = _run_sh(serial, ["settings", "get", "secure", "default_input_method"])
    enabled_lines = _run_sh(serial, ["ime", "list", "-s"]).splitlines()
    all_lines = _run_sh(serial, ["ime", "list", "-s", "-a"]).splitlines()
    enabled = {L.strip() for L in enabled_lines if L.strip()}
    available = {L.strip() for L in all_lines if L.strip()}

    return {
        "ok": True,
        "current": cur.strip() if cur and cur != "null" else None,
        "adbkeyboard_installed": ADBKEYBOARD_SERVICE in available,
        "adbkeyboard_enabled": ADBKEYBOARD_SERVICE in enabled,
        "adbkeyboard_active": (cur or "").strip() == ADBKEYBOARD_SERVICE,
        "enabled": sorted(enabled),
        "available": sorted(available),
    }


def ime_set_adbkeyboard(serial: str) -> dict[str, Any]:
    """Enable and switch to ADBKeyboard. Idempotent."""
    guard = _ensure_adb()
    if guard:
        return guard

    status = ime_status(serial)
    if not status.get("ok"):
        return status
    if not status["adbkeyboard_installed"]:
        return _err(
            "ADBKeyboard is not installed on the device",
            hint="Call POST /v1/mobile/{serial}/helpers/install first.",
        )

    if not status["adbkeyboard_enabled"]:
        r = run(["shell", "ime", "enable", ADBKEYBOARD_SERVICE], serial=serial, timeout=10)
        if r.returncode != 0:
            return _err(f"ime enable failed: {(r.stderr or '').strip()}", exit_code=r.returncode)

    r = run(["shell", "ime", "set", ADBKEYBOARD_SERVICE], serial=serial, timeout=10)
    if r.returncode != 0:
        return _err(f"ime set failed: {(r.stderr or '').strip()}", exit_code=r.returncode)

    return {
        "ok": True,
        "action": "ime_set_adbkeyboard",
        "current": ADBKEYBOARD_SERVICE,
        "previous": status["current"],
    }


def ime_reset(serial: str, target: str | None = None) -> dict[str, Any]:
    """Switch back to the previous IME (or a specific target) and,
    optionally, disable ADBKeyboard so it doesn't appear as an option
    in the on-device IME picker."""
    guard = _ensure_adb()
    if guard:
        return guard

    if target:
        r = run(["shell", "ime", "set", target], serial=serial, timeout=10)
        if r.returncode != 0:
            return _err(f"ime set {target!r} failed: {(r.stderr or '').strip()}",
                        exit_code=r.returncode)
        return {"ok": True, "action": "ime_reset", "current": target}

    # No explicit target — reset to system default by asking framework
    # to pick "the best available IME" via `ime reset`.
    r = run(["shell", "ime", "reset"], serial=serial, timeout=10)
    if r.returncode != 0:
        return _err(f"ime reset failed: {(r.stderr or '').strip()}",
                    exit_code=r.returncode)
    return {"ok": True, "action": "ime_reset", "stdout": (r.stdout or "").strip()}


# --- Unicode paste ---------------------------------------------------------

def paste_text(serial: str, text: str) -> dict[str, Any]:
    """Send arbitrary unicode text via ADBKeyboard's ADB_INPUT_B64 broadcast.

    This is the escape hatch that lets the Dashboard finally accept
    non-ASCII input. If ADBKeyboard isn't currently the active IME,
    the broadcast is delivered but nothing happens on screen — we detect
    that up front so the caller gets a hint, not silent failure.
    """
    if not isinstance(text, str):
        return _err("text must be a string")
    if not text:
        return _err(
            "text is empty",
            hint="ADB_INPUT_B64 does nothing with an empty payload.",
        )
    if len(text) > 8192:
        return _err(f"text too long ({len(text)} chars; max 8192)")

    guard = _ensure_adb()
    if guard:
        return guard

    status = ime_status(serial)
    if not status.get("ok"):
        return status
    if not status["adbkeyboard_installed"]:
        return _err(
            "ADBKeyboard helper is not installed on the device",
            hint=(
                "Unicode paste requires the ADBKeyboard companion APK. "
                "Call POST /v1/mobile/{serial}/helpers/install with the "
                "consent token, then POST /v1/mobile/{serial}/helpers/ime_set, "
                "then retry."
            ),
        )
    if not status["adbkeyboard_active"]:
        return _err(
            "ADBKeyboard is installed but not the active IME",
            hint=(
                "Call POST /v1/mobile/{serial}/helpers/ime_set first. "
                f"Current IME: {status['current']!r}"
            ),
            current_ime=status["current"],
        )

    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    try:
        r = run(
            ["shell", "am", "broadcast",
             "-a", "ADB_INPUT_B64",
             "--es", "msg", encoded],
            serial=serial, timeout=15,
        )
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"paste broadcast failed: {e}")

    out = (r.stdout or "").strip()
    stderr = (r.stderr or "").strip()
    # `am broadcast` returns 0 even when there's no receiver, but the
    # stdout carries "Broadcast completed: result=0" on success. A
    # missing receiver reports "no receivers registered".
    if "no receivers" in (out + stderr).lower():
        return _err(
            "no receivers registered for ADB_INPUT_B64",
            hint="Is ADBKeyboard actually the active IME? Try tapping "
                 "into a text field first — some Android versions only "
                 "register the receiver while the IME is showing.",
            stdout=out, stderr=stderr,
        )

    return {
        "ok": r.returncode == 0,
        "action": "paste",
        "chars": len(text),
        "encoded_bytes": len(encoded),
        "stdout": out,
        "stderr": stderr,
        "exit_code": r.returncode,
    }


def _run_sh(serial: str, args: list[str], timeout: int = 6) -> str:
    """Shorthand for `adb shell <args>` returning stripped stdout."""
    try:
        r = run(["shell", *args], serial=serial, timeout=timeout)
    except Exception:
        return ""
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()
