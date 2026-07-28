"""Fail-closed runner for agent-authored code (posture cubes).

``build_command`` / ``resolve`` are pure-ish (their host capability checks are
small helpers that tests can monkeypatch) so the per-platform enforcement can be
unit-tested without executing arbitrary code. ``run_code_sync`` writes the code
to a per-run scratch dir, engages whatever OS isolation the platform can actually
provide for the active posture, and is **fail-closed**: when the posture demands
a sandbox the platform cannot engage, execution is refused (never silently
unfenced). Environment secrets are scrubbed and wall-timeout + output-cap are
applied on EVERY path, including the unfenced one.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from arena.autonomy.posture import DEFAULT_RESOURCES, DEFAULT_RUNTIMES

_BLOCKED_ENV = ("ARENA_TOKEN", "TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL")
_EXT = {"python3": "py", "python": "py", "node": "js", "sh": "sh", "bash": "sh"}


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _appcontainer_script() -> Path:
    return _repo_root() / "scripts" / "appcontainer_run.ps1"


def _powershell() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")


def _resolve_runtime(lang: str) -> str | None:
    return shutil.which(lang)


def _runtime_grant_dir(exe: str) -> str:
    """Return the narrow runtime root the AppContainer may read/execute.

    For Python/Node this is normally the install directory containing the exe,
    DLLs and stdlib/runtime files.  This is intentionally not the user's home;
    if a runtime is installed inside the profile we grant only that runtime
    subtree, not the whole profile.
    """
    return str(Path(exe).resolve().parent)


def resolve(platform: str, posture: dict[str, Any]) -> dict[str, Any]:
    """Map the posture's sandbox intent to a platform action + support flag."""
    sb = posture.get("sandbox", "off")
    if sb == "off":
        return {"sandbox_action": "off", "supported": True,
                "note": "UNFENCED: code runs on the host with your privileges "
                        "(the labeled extreme posture you selected)."}
    if sb == "microvm":
        return {"sandbox_action": "microvm", "supported": False,
                "note": "microVM isolation is a later slice. Refusing to run unfenced."}
    if platform == "win32":
        script = _appcontainer_script()
        ps = _powershell()
        if not script.exists():
            return {"sandbox_action": "appcontainer", "supported": False,
                    "note": f"AppContainer runner script is missing: {script}. "
                            "Refusing to run unfenced."}
        if not ps:
            return {"sandbox_action": "appcontainer", "supported": False,
                    "note": "PowerShell is not available; cannot engage the "
                            "Windows AppContainer runner. Refusing to run unfenced."}
        return {"sandbox_action": "appcontainer", "supported": True,
                "note": "Windows AppContainer engaged with no capabilities; "
                        "scratch dir is granted modify access, runtime root is "
                        "granted read/execute, stdout/stderr are captured through "
                        "inheritable handles."}
    if sb == "appcontainer":
        return {"sandbox_action": "appcontainer", "supported": False,
                "note": "AppContainer is Windows-only. Refusing to run unfenced "
                        "on this platform."}
    # sb == systemd on posix
    if not _have("systemd-run"):
        return {"sandbox_action": "systemd", "supported": False,
                "note": "systemd-run is not available on this host. Refusing to "
                        "run unfenced."}
    return {"sandbox_action": "systemd", "supported": True, "note": ""}


def _always_enforced() -> dict[str, bool]:
    return {"secrets_scrub": True, "wall_timeout": True, "output_cap": True}


def build_command(platform: str, posture: dict[str, Any], lang: str,
                  code_path: Path, scratch_dir: Path) -> tuple[list[str] | None, dict[str, Any]]:
    """Return (argv, info). argv is None when execution is refused (fail-closed).

    ``info`` always carries ``refused``, ``sandbox_action``, ``enforced`` (the
    axes this invocation actually confines) and ``note`` -- the honest record
    of what the fence does on this platform.
    """
    res = resolve(platform, posture)
    base = [lang, str(code_path)]
    always = _always_enforced()
    if not res["supported"]:
        return None, {"refused": True, "sandbox_action": res["sandbox_action"],
                      "enforced": {**always, "network": False, "privilege": False,
                                   "filesystem_confined": False, "memory": False},
                      "note": res["note"]}
    if res["sandbox_action"] == "off":
        return base, {"refused": False, "sandbox_action": "off",
                      "enforced": {**always, "network": False, "privilege": False,
                                   "filesystem_confined": False, "memory": False},
                      "note": res["note"]}
    if res["sandbox_action"] == "appcontainer":
        exe = _resolve_runtime(lang)
        if not exe:
            return None, {"refused": True, "sandbox_action": "appcontainer",
                          "enforced": {**always, "network": False, "privilege": False,
                                       "filesystem_confined": False, "memory": False},
                          "note": f"runtime '{lang}' was allowed by posture but was "
                                  "not found on PATH. Refusing to run unfenced."}
        resources = posture.get("resources", DEFAULT_RESOURCES)
        wall = int(resources.get("wall_seconds", 60))
        ps = _powershell()
        if not ps:
            return None, {"refused": True, "sandbox_action": "appcontainer",
                          "enforced": {**always, "network": False, "privilege": False,
                                       "filesystem_confined": False, "memory": False},
                          "note": "PowerShell disappeared before command build; "
                                  "refusing to run unfenced."}
        argv = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(_appcontainer_script()),
                "-ApplicationPath", exe,
                "-ScratchDir", str(scratch_dir),
                "-RuntimeGrantDir", _runtime_grant_dir(exe),
                "-TimeoutSec", str(wall),
                "-Arguments", str(code_path)]
        enforced = {
            **always,
            # No AppContainer capabilities are supplied, so network is denied.
            "network": True,
            # Lowbox token.  Not equivalent to a VM, but it is a real Windows
            # privilege boundary and is stricter than normal/admin host exec.
            "privilege": True,
            # AppContainer filesystem access is default-deny for user data; we
            # grant only scratch(M) + runtime(RX).  It can still read normal
            # world-readable system files, so the note stays explicit.
            "filesystem_confined": True,
            # Python still owns the wall timeout; AppContainer has no per-process
            # memory cap in this slice.
            "memory": False,
        }
        notes = [res["note"]]
        if posture.get("network") == "open":
            notes.append("network=open requested, but AppContainer slice denies "
                         "network because no capabilities are granted")
        if posture.get("filesystem") in ("home-read", "host-rw"):
            notes.append("filesystem request is enforced stricter as scratch-only "
                         "+ runtime read/execute on Windows AppContainer")
        return argv, {"refused": False, "sandbox_action": "appcontainer",
                      "enforced": enforced, "note": "; ".join(n for n in notes if n)}

    # systemd strict fixed fence (slice 1: per-axis granularity is slice 2)
    net = posture.get("network", "deny")
    priv = posture.get("privilege", "drop")
    fs = posture.get("filesystem", "scratch-only")
    resources = posture.get("resources", DEFAULT_RESOURCES)
    flags = ["--scope", "--user", "--quiet", "--pipe",
             "--property=TimeoutStopSec=5",
             f"--property=MemoryMax={int(resources.get('memory_mb', 256))}M",
             "--property=CPUQuota=100%"]
    if net in ("deny", "allowlist"):  # allowlist enforced as full deny (stricter, safe)
        flags.append("--property=PrivateNetwork=yes")
    if priv == "drop":
        flags.append("--property=DynamicUser=yes")
    if fs in ("scratch-only", "home-read"):
        flags.append("--property=ProtectSystem=strict")
        flags.append(f"--property=ReadWritePaths={scratch_dir}")
        if fs == "home-read":
            flags.append(f"--property=BindReadOnlyPaths={Path.home()}")
    enforced = {
        **always,
        "network": net in ("deny", "allowlist"),
        "privilege": priv == "drop",
        "filesystem_confined": fs in ("scratch-only", "home-read"),
        "memory": True,
    }
    notes = []
    if net == "allowlist":
        notes.append("network allowlist enforced as full deny in slice 1")
    argv = ["systemd-run", *flags, "--", *base]
    return argv, {"refused": False, "sandbox_action": "systemd",
                  "enforced": enforced, "note": "; ".join(notes)}


def _scrub_env() -> dict[str, str]:
    clean = {k: v for k, v in os.environ.items()
             if not any(b in k.upper() for b in _BLOCKED_ENV)}
    clean["ARENA_SANDBOX"] = "1"
    return clean


def run_code_sync(code: str, lang: str, posture: dict[str, Any], *,
                  timeout: int | None = None, platform: str | None = None,
                  env: dict[str, str] | None = None) -> dict[str, Any]:
    platform = platform or sys.platform
    allow = posture.get("runtimes") or list(DEFAULT_RUNTIMES)
    if posture.get("runtime") != "any" and lang not in allow:
        return {"ok": False, "refused": True,
                "error": f"runtime '{lang}' not in posture runtimes allowlist {allow}"}
    effective_posture = posture
    if timeout is not None:
        # The outer Python subprocess timeout is not enough for Windows: if it
        # kills PowerShell, the lowbox child may survive until the script's own
        # timeout.  Propagate the caller's wall limit into the platform command
        # before building it, so the fence owner terminates the child first.
        effective_posture = dict(posture)
        res = dict(posture.get("resources", DEFAULT_RESOURCES))
        res["wall_seconds"] = int(timeout)
        effective_posture["resources"] = res
    scratch = Path(tempfile.mkdtemp(prefix="arena-code-"))
    code_path = scratch / f"code-{uuid.uuid4().hex[:8]}.{_EXT.get(lang, 'txt')}"
    code_path.write_text(code, encoding="utf-8")
    try:
        argv, info = build_command(platform, effective_posture, lang, code_path, scratch)
        if info.get("refused"):
            return {"ok": False, **info}
        wall = timeout or int(effective_posture.get("resources", DEFAULT_RESOURCES)
                              .get("wall_seconds", 60))
        max_out = int(effective_posture.get("resources", DEFAULT_RESOURCES)
                      .get("output_bytes", 100 * 1024))
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=wall + (5 if info["sandbox_action"] == "appcontainer" else 0),
                                  env=(env if env is not None else _scrub_env()))
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or b"") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            err = (exc.stderr or b"") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return {"ok": False, "timed_out": True, "exit_code": None,
                    "stdout": _trim(out, max_out), "stderr": _trim(err, max_out // 2),
                    "sandbox_action": info["sandbox_action"], "enforced": info["enforced"],
                    "note": info.get("note", "")}
        return {
            "ok": proc.returncode == 0, "exit_code": proc.returncode,
            "stdout": _trim(proc.stdout, max_out),
            "stderr": _trim(proc.stderr, max_out // 2),
            "sandbox_action": info["sandbox_action"], "enforced": info["enforced"],
            "note": info.get("note", ""),
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _trim(s: Any, n: int) -> str:
    text = s if isinstance(s, str) else (s.decode("utf-8", "replace") if s else "")
    if len(text) > n:
        return text[:n] + f"\n...[truncated, {len(text) - n} bytes omitted]"
    return text
