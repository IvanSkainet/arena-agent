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

import base64
import binascii
import json
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


def _managed_runtime_path(lang: str) -> str | None:
    try:
        from arena.workbench.runtimes import _managed_go_path, load_registry
        if lang == "go":
            p = _managed_go_path()
            if p:
                return str(p)
        meta = (load_registry().get("runtimes") or {}).get(lang) or {}
        p = meta.get("path")
        return str(p) if p and Path(str(p)).exists() else None
    except Exception:
        return None


def _resolve_runtime(lang: str) -> str | None:
    return shutil.which(lang) or _managed_runtime_path(lang)


def _is_windowsapps_alias(path: str | None) -> bool:
    if not path:
        return False
    return "\\microsoft\\windowsapps\\" in str(path).replace("/", "\\").lower()


def _resolve_win32_runtime(lang: str) -> str | None:
    """Resolve a real Windows runtime, avoiding App Execution Alias shims.

    ``python3`` commonly resolves to ``%LOCALAPPDATA%\\Microsoft\\WindowsApps``
    on Windows. That shim is not a real interpreter and fails inside
    AppContainer with exit code 9009. Prefer a real Python discovered via the
    launcher or a non-WindowsApps ``python.exe`` fallback.
    """
    if lang in {"python", "python3"}:
        py = shutil.which("py.exe") or shutil.which("py")
        if py and not _is_windowsapps_alias(py):
            try:
                proc = subprocess.run(
                    [py, "-3", "-c", "import sys; print(sys.executable)"],
                    capture_output=True, text=True, timeout=5, env=_scrub_env(),
                )
                candidate = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
                if candidate and Path(candidate).exists() and not _is_windowsapps_alias(candidate):
                    return candidate
            except Exception:
                pass
        for name in (lang, "python", "python3"):
            candidate = _resolve_runtime(name)
            if candidate and not _is_windowsapps_alias(candidate):
                return candidate
        return None
    candidate = _resolve_runtime(lang)
    if _is_windowsapps_alias(candidate):
        return None
    return candidate


def _runtime_grant_dir(exe: str) -> str:
    """Return the narrow runtime root the AppContainer may read/execute.

    For Python/Node this is normally the install directory containing the exe,
    DLLs and stdlib/runtime files. For managed Go, grant the Go root (parent of
    bin/) so the tool can read pkg/src metadata as GOROOT. This is intentionally
    not the user's home; if a runtime is installed inside the profile we grant
    only that runtime subtree, not the whole profile.
    """
    p = Path(exe).resolve()
    if p.name.lower() in {"go.exe", "go"} and p.parent.name.lower() == "bin":
        return str(p.parent.parent)
    return str(p.parent)


def _runtime_invocation(lang: str, command: str, code_path: Path, runtime_args: list[str] | None = None) -> list[str]:
    args = [str(a) for a in (runtime_args or [])]
    if lang == "go":
        return [command, "run", str(code_path), *args]
    return [command, str(code_path), *args]


def _managed_go_root() -> str | None:
    p = _managed_runtime_path("go")
    if not p:
        return None
    exe = Path(p).resolve()
    if exe.parent.name.lower() == "bin":
        return str(exe.parent.parent)
    return None


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
                  code_path: Path, scratch_dir: Path,
                  runtime_args: list[str] | None = None,
                  stdin_path: Path | None = None) -> tuple[list[str] | None, dict[str, Any]]:
    """Return (argv, info). argv is None when execution is refused (fail-closed).

    ``info`` always carries ``refused``, ``sandbox_action``, ``enforced`` (the
    axes this invocation actually confines) and ``note`` -- the honest record
    of what the fence does on this platform.
    """
    res = resolve(platform, posture)
    runtime_cmd = _managed_runtime_path(lang) or lang
    base = _runtime_invocation(lang, runtime_cmd, code_path, runtime_args)
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
        if platform == "win32" and lang == "go":
            return None, {"refused": True, "sandbox_action": "appcontainer",
                          "enforced": {**always, "network": False, "privilege": False,
                                       "filesystem_confined": False, "memory": False},
                          "note": "Managed Go is installed, but the Go toolchain opens the Windows NUL device during compilation; Windows AppContainer denies that device. Refusing fenced Go until a broker/device policy exists. Use an operator-selected sandbox=off posture for host Go builds."}
        exe = _resolve_win32_runtime(lang) if platform == "win32" else _resolve_runtime(lang)
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
                "-ArgumentsJson", json.dumps(_runtime_invocation(lang, exe, code_path, runtime_args)[1:])]
        if stdin_path is not None:
            argv.extend(["-StdinPath", str(stdin_path)])
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


def _safe_rel_path(value: str) -> Path:
    rel = Path(str(value).replace("\\", "/"))
    if not str(value).strip() or rel.is_absolute() or any(part in ("..", "") for part in rel.parts):
        raise ValueError(f"unsafe relative path: {value!r}")
    if rel.drive or str(rel).startswith(("/", "\\")):
        raise ValueError(f"unsafe relative path: {value!r}")
    return rel


def _write_workspace_files(scratch: Path, files: list[dict[str, Any]] | None) -> list[str]:
    written: list[str] = []
    for item in files or []:
        if not isinstance(item, dict):
            raise ValueError("each workspace file must be an object")
        rel = _safe_rel_path(str(item.get("path") or ""))
        target = scratch / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        encoding = str(item.get("encoding") or "utf-8").lower()
        content = item.get("content", "")
        if encoding == "base64":
            if not isinstance(content, str):
                raise ValueError("base64 file content must be a string")
            target.write_bytes(base64.b64decode(content))
        else:
            if not isinstance(content, str):
                raise ValueError("text file content must be a string")
            target.write_text(content, encoding="utf-8")
        written.append(rel.as_posix())
    return written


def _persist_artifacts(run_id: str, scratch: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    try:
        from arena.workbench.artifacts import persist_run
        return persist_run(run_id, scratch, items)
    except Exception:
        return items


def _artifact_manifest(scratch: Path, patterns: list[str] | None, *, max_each: int = 64 * 1024,
                       max_count: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for pat in patterns or []:
        rel_pat = str(pat or "").replace("\\", "/")
        if not rel_pat or rel_pat.startswith(("/", "..")) or "/../" in f"/{rel_pat}/":
            continue
        for fp in sorted(scratch.glob(rel_pat)):
            if len(out) >= max_count:
                return out
            if not fp.is_file() or fp in seen:
                continue
            seen.add(fp)
            rel = fp.relative_to(scratch).as_posix()
            data = fp.read_bytes()
            item: dict[str, Any] = {"path": rel, "bytes": len(data)}
            sample = data[:max_each]
            try:
                text = sample.decode("utf-8")
                item["text"] = text
                item["truncated"] = len(data) > max_each
            except UnicodeDecodeError:
                item["base64"] = base64.b64encode(sample).decode("ascii")
                item["truncated"] = len(data) > max_each
            out.append(item)
    return out


def run_code_sync(code: str, lang: str, posture: dict[str, Any], *,
                  timeout: int | None = None, platform: str | None = None,
                  env: dict[str, str] | None = None,
                  files: list[dict[str, Any]] | None = None,
                  entry: str | None = None,
                  argv: list[str] | None = None,
                  stdin: str | None = None,
                  artifacts: list[str] | None = None,
                  deps: dict[str, Any] | None = None) -> dict[str, Any]:
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
    run_id = uuid.uuid4().hex
    try:
        try:
            workspace_files = _write_workspace_files(scratch, files)
            if entry:
                code_path = scratch / _safe_rel_path(entry)
                if not code_path.exists():
                    return {"ok": False, "refused": True,
                            "error": f"entry file does not exist in workspace: {entry}"}
            else:
                code_path = scratch / f"code-{uuid.uuid4().hex[:8]}.{_EXT.get(lang, 'txt')}"
                code_path.write_text(code, encoding="utf-8")
                workspace_files = [*workspace_files, code_path.relative_to(scratch).as_posix()]
        except (ValueError, OSError, binascii.Error) as e:
            return {"ok": False, "refused": True, "error": f"invalid workspace: {e}"}

        wall = timeout or int(effective_posture.get("resources", DEFAULT_RESOURCES)
                              .get("wall_seconds", 60))
        from arena.autonomy.deps import install_deps
        deps_result = install_deps(
            scratch, platform, lang, deps, effective_posture, wall,
            resolve_runtime=_resolve_runtime, resolve_win32_runtime=_resolve_win32_runtime,
            managed_go_root=_managed_go_root, scrub_env=_scrub_env, trim=_trim,
        )
        if not deps_result.get("ok"):
            return {"ok": False, "refused": True, "error": deps_result.get("error"), "deps": deps_result}

        runtime_args = [str(a) for a in (argv or [])]
        stdin_path = None
        if stdin is not None:
            stdin_path = scratch / "stdin.txt"
            stdin_path.write_text(stdin, encoding="utf-8")
        argv_cmd, info = build_command(
            platform, effective_posture, lang, code_path, scratch,
            runtime_args=runtime_args, stdin_path=stdin_path,
        )
        if info.get("refused"):
            return {"ok": False, **info}
        max_out = int(effective_posture.get("resources", DEFAULT_RESOURCES)
                      .get("output_bytes", 100 * 1024))
        run_env = env if env is not None else _scrub_env()
        py_deps = deps_result.get("python") or {}
        if py_deps.get("path"):
            run_env = dict(run_env)
            old_py_path = run_env.get("PYTHONPATH", "")
            run_env["PYTHONPATH"] = py_deps["path"] + (os.pathsep + old_py_path if old_py_path else "")
        npm_deps = deps_result.get("npm") or {}
        if npm_deps.get("path"):
            run_env = dict(run_env)
            old_node_path = run_env.get("NODE_PATH", "")
            run_env["NODE_PATH"] = npm_deps["path"] + (os.pathsep + old_node_path if old_node_path else "")
        if lang == "go":
            from arena.autonomy.deps import go_env_for_scratch
            go_env = go_env_for_scratch(scratch, _managed_go_root, _scrub_env)
            merged = dict(run_env)
            merged.update(go_env)
            run_env = merged
        try:
            proc = subprocess.run(argv_cmd, capture_output=True, text=True,
                                  input=stdin if stdin is not None else None,
                                  timeout=wall + (5 if info["sandbox_action"] == "appcontainer" else 0),
                                  env=run_env, cwd=str(scratch))
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or b"") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            err = (exc.stderr or b"") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return {"ok": False, "timed_out": True, "exit_code": None,
                    "stdout": _trim(out, max_out), "stderr": _trim(err, max_out // 2),
                    "sandbox_action": info["sandbox_action"], "enforced": info["enforced"],
                    "note": info.get("note", ""), "workspace_files": workspace_files,
                    "run_id": run_id, "deps": deps_result,
                    "artifacts": _persist_artifacts(run_id, scratch, _artifact_manifest(scratch, artifacts))}
        return {
            "ok": proc.returncode == 0, "exit_code": proc.returncode,
            "stdout": _trim(proc.stdout, max_out),
            "stderr": _trim(proc.stderr, max_out // 2),
            "sandbox_action": info["sandbox_action"], "enforced": info["enforced"],
            "note": info.get("note", ""),
            "workspace_files": workspace_files,
            "run_id": run_id,
            "deps": deps_result,
            "artifacts": _persist_artifacts(run_id, scratch, _artifact_manifest(scratch, artifacts)),
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _trim(s: Any, n: int) -> str:
    text = s if isinstance(s, str) else (s.decode("utf-8", "replace") if s else "")
    if len(text) > n:
        return text[:n] + f"\n...[truncated, {len(text) - n} bytes omitted]"
    return text
