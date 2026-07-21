"""MCP net.* tools: typed HTTP client + secrets store + sudo runner.

Introduced in v4.57.0.

Rationale — before this release, scenarios had to fall back to
``exec "curl ..."`` for anything network-shaped: hitting an external
API (Groq, HuggingFace, webhook targets), downloading a file, POSTing
JSON. That made every network step ``dangerous`` (exec-level risk) and
opaque to the policy layer.

``net.http`` is a typed replacement:
  - only http/https schemes (uses arena.security_ssrf._validate_url so
    it inherits the same allow-list as browser.read),
  - JSON body or raw text body, optional bearer/basic auth,
  - response body is size-capped and either returned as text (when
    Content-Type is textual) or base64 (binary),
  - timeout is bounded [1s, 60s].

``secrets.get`` reads a single key from ``~/.arena/secrets.json`` so
scenarios can pass an API key to net.http without leaking it in the
step ``arguments`` block that gets logged in ``mission.json.runs[]``.

``sudo.run`` wraps ``sudo -n <cmd>`` — the safe non-interactive path
that /v1/exec has always allowed (see arena/security_commands.py
"non-interactive sudo is allowed"). It exists as a separate tool so
scenarios and the extension can classify it as ``dangerous`` and
require explicit approval, rather than hiding sudo inside a general
``exec`` call.
"""
from __future__ import annotations

import base64
import json
import os
import platform
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.security_ssrf import _validate_url


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MiB cap on returned body
_DEFAULT_TIMEOUT = 20.0
_MAX_TIMEOUT = 60.0
_MIN_TIMEOUT = 1.0

_TEXTUAL_MIME_PREFIXES = ("text/", "application/json", "application/xml",
                          "application/javascript", "application/x-yaml",
                          "application/yaml")


def _err(msg: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {msg}"}]}


def _clamp_timeout(raw: Any) -> float:
    try:
        t = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT
    if t < _MIN_TIMEOUT:
        return _MIN_TIMEOUT
    if t > _MAX_TIMEOUT:
        return _MAX_TIMEOUT
    return t


def _secrets_path() -> Path:
    override = os.environ.get("ARENA_SECRETS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".arena" / "secrets.json"


def _load_secrets() -> dict[str, Any]:
    path = _secrets_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _handle_net_http(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url", "") or "").strip()
    if not url:
        return _err("missing 'url' argument")
    invalid = _validate_url(url)
    if invalid:
        return _err(f"URL rejected: {invalid}")

    method = str(args.get("method", "GET") or "GET").upper()
    if method not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"):
        return _err(f"method '{method}' not allowed")

    timeout = _clamp_timeout(args.get("timeout"))

    # Headers
    headers: dict[str, str] = {}
    raw_headers = args.get("headers") or {}
    if isinstance(raw_headers, dict):
        for k, v in raw_headers.items():
            headers[str(k)] = str(v)

    # Auth shortcuts. Value can be a literal token OR a `secret:<name>`
    # reference that pulls from secrets.json without exposing it in
    # scenario arguments.
    auth = args.get("auth")
    if isinstance(auth, dict):
        atype = str(auth.get("type", "") or "").lower()
        aval = str(auth.get("value", "") or "")
        if aval.startswith("secret:"):
            key = aval[len("secret:"):]
            aval = str(_load_secrets().get(key, ""))
            if not aval:
                return _err(f"auth secret '{key}' not found in {_secrets_path()}")
        if atype == "bearer" and aval:
            headers["Authorization"] = f"Bearer {aval}"
        elif atype == "basic" and aval:
            headers["Authorization"] = f"Basic {aval}"
        elif atype and atype not in ("bearer", "basic"):
            return _err(f"auth.type '{atype}' not supported (bearer|basic)")

    # Body: json | text | base64. json wins if present.
    body_bytes: bytes | None = None
    if "json" in args and args["json"] is not None:
        try:
            body_bytes = json.dumps(args["json"]).encode("utf-8")
        except (TypeError, ValueError) as e:
            return _err(f"json body serialisation: {e}")
        headers.setdefault("Content-Type", "application/json")
    elif "text" in args and args["text"] is not None:
        body_bytes = str(args["text"]).encode("utf-8")
        headers.setdefault("Content-Type", "text/plain; charset=utf-8")
    elif "base64" in args and args["base64"]:
        try:
            body_bytes = base64.b64decode(str(args["base64"]))
        except (ValueError, TypeError) as e:
            return _err(f"base64 body decode: {e}")

    # For query params on GET/HEAD/DELETE
    params = args.get("params") or {}
    if isinstance(params, dict) and params:
        clean = {str(k): str(v) for k, v in params.items() if v not in (None, "")}
        if clean:
            sep = "&" if urllib.parse.urlparse(url).query else "?"
            url = f"{url}{sep}{urllib.parse.urlencode(clean)}"

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- SSRF-validated user URL, timeout bounded  # nosemgrep: dynamic-urllib-use-detected -- URL passes through arena.security_ssrf._validate_url on line above
            status = resp.status
            mime = resp.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip().lower()
            raw = resp.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as e:
        status = e.code
        mime = (e.headers or {}).get("Content-Type", "text/plain").split(";", 1)[0].strip().lower()
        try:
            raw = e.read(_MAX_RESPONSE_BYTES + 1)
        except Exception:  # pragma: no cover
            raw = b""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"ok": False, "error": f"network error: {e}", "url": url, "method": method}

    truncated = len(raw) > _MAX_RESPONSE_BYTES
    if truncated:
        raw = raw[:_MAX_RESPONSE_BYTES]

    is_textual = any(mime.startswith(p) for p in _TEXTUAL_MIME_PREFIXES)
    result: dict[str, Any] = {
        "ok": 200 <= status < 400,
        "status": status,
        "url": url,
        "method": method,
        "mime": mime,
        "size_bytes": len(raw),
        "truncated": truncated,
    }
    if is_textual:
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:
            text = raw.decode("latin-1", "replace")
        result["text"] = text
        if mime == "application/json":
            try:
                result["json"] = json.loads(text)
            except (ValueError, TypeError):
                pass
    else:
        result["base64"] = base64.b64encode(raw).decode("ascii")
    return result


def _handle_secrets_get(args: dict[str, Any]) -> dict[str, Any]:
    key = str(args.get("key", "") or "").strip()
    if not key:
        return _err("missing 'key' argument")
    secrets = _load_secrets()
    if key not in secrets:
        return {"ok": False, "error": f"secret '{key}' not found", "path": str(_secrets_path())}
    val = secrets[key]
    # Never return the raw value in cleartext — return a redacted preview
    # and a base64 form. Callers that need the plaintext should reference
    # it as ``secret:<key>`` inside net.http.auth.value which resolves
    # server-side without echoing the value back over the wire.
    text = str(val)
    preview = (text[:2] + "***" + text[-2:]) if len(text) > 8 else "***"
    return {
        "ok": True,
        "key": key,
        "length": len(text),
        "preview": preview,
        "path": str(_secrets_path()),
    }


def _handle_secrets_list(_args: dict[str, Any]) -> dict[str, Any]:
    secrets = _load_secrets()
    return {"ok": True, "keys": sorted(secrets.keys()), "path": str(_secrets_path())}


def _handle_sudo_run(args: dict[str, Any], *, ctx, run_sd) -> dict[str, Any]:
    """Run a command through ``sudo -n`` (non-interactive) on POSIX.

    v4.60.6: runs subprocess directly instead of routing through the
    run_sd sandbox. sudo.run is already classified `dangerous` at
    the extension policy layer and requires explicit operator
    approval; the extra sd-exec cgroup layer added nothing but a
    PermissionError on setups where the sd-exec wrapper isn't
    executable in every context (v4.59.0 bug).

    BLOCK_PATTERNS still apply — every dangerous rm/mkfs/dd pattern
    is caught before subprocess starts.
    """
    import subprocess as _sp
    cmd = str(args.get("cmd", "") or "").strip()
    if not cmd:
        return _err("missing 'cmd' argument")
    if platform.system() == "Windows":
        return _err("sudo.run is POSIX-only. Use admin.run for Windows/macOS/Linux uniformity.")
    full = f"sudo -n {cmd}"
    block = ctx.blocked_reason(full)
    if block:
        return _err(f"blocked: {block}")
    timeout = _clamp_timeout(args.get("timeout")) if args.get("timeout") else 30.0
    try:
        proc = _sp.run(  # nosec B603 -- sudo entrypoint, BLOCK_PATTERNS gate applied above # nosemgrep: dangerous-subprocess-use-audit
            ["sudo", "-n", "bash", "-lc", cmd],
            capture_output=True, text=True, timeout=int(timeout) or 30,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except _sp.TimeoutExpired:
        return {"ok": False, "error": f"sudo.run timed out after {int(timeout) or 30}s"}
    except FileNotFoundError:
        return {"ok": False, "error": "sudo not found on PATH"}
    return {
        "ok": rc == 0,
        "exit": rc,
        "stdout": out[-15000:],
        "stderr": err[-5000:],
        "sudo_hint": (
            "sudo requires NOPASSWD for the target command in /etc/sudoers "
            "(or /etc/sudoers.d/) so `sudo -n` can succeed non-interactively"
            if rc != 0 and "a password is required" in (err or "").lower()
            else None
        ),
    }


def _handle_admin_run(args: dict[str, Any], *, ctx) -> dict[str, Any]:
    """Cross-platform admin escalation.

    v4.60.6: unifies POSIX sudo, Windows UAC, and macOS Touch ID under
    one MCP tool name so scenarios don't need to platform-branch.

    Behaviour per OS:
      * Linux: proxies to sudo -n (same as sudo.run)
      * macOS: osascript "do shell script ... with administrator privileges"
        which prompts Touch ID / password via GUI dialog
      * Windows: if already elevated, runs directly; else calls
        `powershell Start-Process -Verb RunAs -Wait -WindowStyle Hidden`
        which pops the UAC prompt. Non-interactive Windows admin
        requires an external supervisor (Task Scheduler with
        `/RL HIGHEST` + `/RU SYSTEM`) which is out of scope here.
    """
    import subprocess as _sp
    cmd = str(args.get("cmd", "") or "").strip()
    if not cmd:
        return _err("missing 'cmd' argument")
    sysname = platform.system()
    timeout = _clamp_timeout(args.get("timeout")) if args.get("timeout") else 30.0
    block = ctx.blocked_reason(cmd) if hasattr(ctx, "blocked_reason") else None
    if block:
        return _err(f"blocked: {block}")

    if sysname == "Linux":
        return _handle_sudo_run(args, ctx=ctx, run_sd=None)

    if sysname == "Darwin":
        # osascript uses shell-inside-AppleScript; we embed cmd as a
        # quoted string and let AppleScript run it with elevation.
        # Escaping: double any " and \ inside cmd.
        safe = cmd.replace("\\", "\\\\").replace('"', '\\"')
        script = f'do shell script "{safe}" with administrator privileges'
        try:
            proc = _sp.run(  # nosec B603 -- osascript entrypoint, BLOCK_PATTERNS gate applied above # nosemgrep: dangerous-subprocess-use-audit
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=int(timeout) or 30,
            )
        except _sp.TimeoutExpired:
            return {"ok": False, "error": f"admin.run (osascript) timed out after {int(timeout) or 30}s"}
        except FileNotFoundError:
            return {"ok": False, "error": "osascript not found (are you on macOS?)"}
        return {
            "ok": proc.returncode == 0,
            "exit": proc.returncode,
            "stdout": proc.stdout[-15000:],
            "stderr": proc.stderr[-5000:],
            "platform": "darwin",
            "prompt_shown": "Touch ID / password (via osascript)",
        }

    if sysname == "Windows":
        # Check if we're already elevated. If yes, no UAC needed.
        try:
            import ctypes
            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_admin = False
        if is_admin:
            try:
                proc = _sp.run(  # nosec B603 -- elevated context, BLOCK_PATTERNS gate applied above # nosemgrep: dangerous-subprocess-use-audit
                    ["cmd", "/c", cmd],
                    capture_output=True, text=True, timeout=int(timeout) or 30,
                )
            except _sp.TimeoutExpired:
                return {"ok": False, "error": f"admin.run timed out after {int(timeout) or 30}s"}
            return {
                "ok": proc.returncode == 0,
                "exit": proc.returncode,
                "stdout": proc.stdout[-15000:],
                "stderr": proc.stderr[-5000:],
                "platform": "windows",
                "elevated": True,
                "note": "process was already elevated; ran directly without UAC prompt",
            }
        # Not elevated. Kick off UAC prompt via Start-Process -Verb RunAs.
        # We can't capture stdout of an elevated child from a non-elevated
        # parent (Windows security boundary), so report status via exit code
        # + a marker file if the caller needs output.
        ps_cmd = (
            "$p = Start-Process -FilePath 'cmd' "
            f"-ArgumentList '/c',{_ps_quote(cmd)} "
            "-Verb RunAs -Wait -PassThru -WindowStyle Hidden; "
            "$p.ExitCode"
        )
        try:
            proc = _sp.run(  # nosec B603 -- ps entrypoint, BLOCK_PATTERNS gate applied above # nosemgrep: dangerous-subprocess-use-audit
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=int(timeout) or 30,
            )
        except _sp.TimeoutExpired:
            return {"ok": False, "error": f"admin.run (UAC) timed out after {int(timeout) or 30}s"}
        elevated_exit = None
        for line in reversed((proc.stdout or "").splitlines()):
            line = line.strip()
            if line.lstrip("-").isdigit():
                elevated_exit = int(line); break
        return {
            "ok": elevated_exit == 0,
            "exit": elevated_exit if elevated_exit is not None else proc.returncode,
            "stdout": proc.stdout[-15000:],
            "stderr": proc.stderr[-5000:],
            "platform": "windows",
            "elevated": False,
            "prompt_shown": "UAC (Windows)",
            "hint": (
                "The elevated child ran in a separate console; its stdout "
                "was not captured due to Windows security boundaries. Have "
                "the command write its own output file if you need it."
            ),
        }

    return _err(f"admin.run: unsupported platform {sysname}")


def _ps_quote(s: str) -> str:
    """Quote a string for PowerShell single-quoted literal (escape ' -> \'\')."""
    return "'" + s.replace("'", "''") + "'"


def handle_net_tool(name: str, args: dict[str, Any], *, ctx, run_sd) -> dict[str, Any] | None:
    if name == "net.http":
        return text_content(json.dumps(_handle_net_http(args), ensure_ascii=False))
    if name == "secrets.get":
        return text_content(json.dumps(_handle_secrets_get(args), ensure_ascii=False))
    if name == "secrets.list":
        return text_content(json.dumps(_handle_secrets_list(args), ensure_ascii=False))
    if name == "sudo.run":
        return text_content(json.dumps(_handle_sudo_run(args, ctx=ctx, run_sd=run_sd), ensure_ascii=False))
    if name == "admin.run":
        return text_content(json.dumps(_handle_admin_run(args, ctx=ctx), ensure_ascii=False))
    return None


__all__ = ["handle_net_tool"]
