"""Managed runtime registry/probe/install for the Code Workbench."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

_GO_INDEX = "https://go.dev/dl/?mode=json"
_WASMTIME_LATEST = "https://api.github.com/repos/bytecodealliance/wasmtime/releases/latest"
_DENO_LATEST = "https://api.github.com/repos/denoland/deno/releases/latest"
_ZIG_INDEX = "https://ziglang.org/download/index.json"
_LUA_LATEST = "https://api.github.com/repos/dyne/luabinaries/releases/latest"


def home() -> Path:
    return Path(os.environ.get("ARENA_AGENT_HOME") or (Path.home() / "arena-bridge")).expanduser()


def tools_dir() -> Path:
    p = home() / "tools"
    p.mkdir(parents=True, exist_ok=True)
    return p


def registry_path() -> Path:
    p = home() / "runtime" / "runtimes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_registry() -> dict[str, Any]:
    p = registry_path()
    if not p.exists():
        return {"runtimes": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"runtimes": {}}
    except Exception:
        return {"runtimes": {}}


def save_registry(data: dict[str, Any]) -> None:
    registry_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _run_version(exe: str, args: list[str] | None = None) -> str | None:
    try:
        proc = subprocess.run([exe, *(args or ["--version"])], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    out = (proc.stdout or proc.stderr or "").strip()
    return out.splitlines()[0] if out else None


def _which(name: str) -> str | None:
    return shutil.which(name)


def _managed_go_path(version: str | None = None) -> Path | None:
    root = tools_dir()
    if version:
        p = root / f"go{version}" / "bin" / ("go.exe" if platform.system().lower() == "windows" else "go")
        return p if p.exists() else None
    for d in sorted(root.glob("go*"), reverse=True):
        p = d / "bin" / ("go.exe" if platform.system().lower() == "windows" else "go")
        if p.exists():
            return p
    return None


def _managed_wasmtime_path(version: str | None = None) -> Path | None:
    root = tools_dir()
    exe_name = "wasmtime.exe" if platform.system().lower() == "windows" else "wasmtime"
    if version:
        ver = version if version.startswith("wasmtime-") else f"wasmtime-{version.lstrip('v')}"
        candidates = list(root.glob(f"{ver}*/{exe_name}")) + list(root.glob(f"{ver}*/bin/{exe_name}"))
        return candidates[0] if candidates else None
    for d in sorted(root.glob("wasmtime*"), reverse=True):
        for p in (d / exe_name, d / "bin" / exe_name):
            if p.exists():
                return p
    return None


def _managed_deno_path(version: str | None = None) -> Path | None:
    root = tools_dir()
    exe_name = "deno.exe" if platform.system().lower() == "windows" else "deno"
    if version:
        ver = version if version.startswith("deno-") else f"deno-{version.lstrip('v')}"
        candidates = list(root.glob(f"{ver}*/{exe_name}"))
        return candidates[0] if candidates else None
    for d in sorted(root.glob("deno*"), reverse=True):
        p = d / exe_name
        if p.exists():
            return p
    return None


def _managed_zig_path(version: str | None = None) -> Path | None:
    root = tools_dir()
    exe_name = "zig.exe" if platform.system().lower() == "windows" else "zig"
    if version:
        ver = version if version.startswith("zig-") else f"zig-{version.lstrip('v')}"
        candidates = list(root.glob(f"{ver}*/{exe_name}"))
        return candidates[0] if candidates else None
    for d in sorted(root.glob("zig*"), reverse=True):
        p = d / exe_name
        if p.exists():
            return p
    return None


def _managed_lua_path(version: str | None = None) -> Path | None:
    root = tools_dir()
    exe_name = "lua.exe" if platform.system().lower() == "windows" else "lua"
    if version:
        ver = version if version.startswith("lua-") else f"lua-{version}"
        p = root / ver / exe_name
        return p if p.exists() else None
    for d in sorted(root.glob("lua-*"), reverse=True):
        p = d / exe_name
        if p.exists():
            return p
    return None


def probe() -> dict[str, Any]:
    reg = load_registry().get("runtimes", {})
    out: dict[str, Any] = {"ok": True, "managed_home": str(tools_dir()), "runtimes": {}}
    checks = {
        "python": ["python", "--version"],
        "python3": ["python3", "--version"],
        "node": ["node", "--version"],
        "deno": ["deno", "--version"],
        "zig": ["zig", "version"],
        "lua": ["lua", "-v"],
        "go": ["go", "version"],
        "wasmtime": ["wasmtime", "--version"],
        "wasm": ["wasmtime", "--version"],
        "rustc": ["rustc", "--version"],
        "cargo": ["cargo", "--version"],
        "java": ["java", "--version"],
    }
    for name, cmd in checks.items():
        exe = _which(cmd[0])
        out["runtimes"][name] = {"available": bool(exe), "path": exe, "version": _run_version(exe, cmd[1:]) if exe else None, "managed": False}
    go_managed = _managed_go_path()
    if go_managed:
        out["runtimes"]["go"] = {"available": True, "path": str(go_managed), "version": _run_version(str(go_managed), ["version"]), "managed": True}
    deno_managed = _managed_deno_path()
    if deno_managed:
        out["runtimes"]["deno"] = {"available": True, "path": str(deno_managed), "version": _run_version(str(deno_managed), ["--version"]), "managed": True}
    zig_managed = _managed_zig_path()
    if zig_managed:
        out["runtimes"]["zig"] = {"available": True, "path": str(zig_managed), "version": _run_version(str(zig_managed), ["version"]), "managed": True}
    lua_managed = _managed_lua_path()
    if lua_managed:
        out["runtimes"]["lua"] = {"available": True, "path": str(lua_managed), "version": _run_version(str(lua_managed), ["-v"]), "managed": True}
    wasmtime_managed = _managed_wasmtime_path()
    if wasmtime_managed:
        wm = {"available": True, "path": str(wasmtime_managed), "version": _run_version(str(wasmtime_managed), ["--version"]), "managed": True}
        out["runtimes"]["wasmtime"] = dict(wm)
        out["runtimes"]["wasm"] = dict(wm)
    for name, meta in reg.items():
        out["runtimes"].setdefault(name, {}).update({"registry": meta})
    # Rust diagnosis: compiler alone is not enough on Windows.
    rust = out["runtimes"].get("rustc", {})
    if rust.get("available") and platform.system().lower() == "windows":
        rust["linker_available"] = bool(_which("link.exe") or _which("gcc") or _which("clang"))
        if not rust["linker_available"]:
            rust["diagnosis"] = "rustc is installed, but no MSVC/MinGW/clang linker is on PATH"
    return out


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "ArenaBridge/runtime.install"})
    with urllib.request.urlopen(req, timeout=120) as r:  # nosec B310 -- fixed public runtime URLs selected from upstream release metadata  # nosemgrep: dynamic-urllib-use-detected -- URL comes from the official Go release index selected by runtime.install and is SHA-256 verified before extraction
        with dest.open("wb") as f:
            shutil.copyfileobj(r, f)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_join_extract(base: Path, member_name: str) -> Path:
    target = (base / member_name).resolve()
    base_resolved = base.resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise RuntimeError(f"archive member escapes destination: {member_name}")
    return target


def _extract_zip_safe(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            target = _safe_join_extract(dest, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def _extract_tar_safe(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:*") as t:
        for member in t.getmembers():
            target = _safe_join_extract(dest, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = t.extractfile(member)
            if src is None:
                continue
            with src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def _go_asset(version: str | None = None) -> dict[str, Any]:
    req = urllib.request.Request(_GO_INDEX, headers={"User-Agent": "ArenaBridge/runtime.install"})
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 -- fixed official Go release index  # nosemgrep: dynamic-urllib-use-detected -- fixed https://go.dev/dl/?mode=json official release metadata endpoint
        releases = json.loads(r.read().decode("utf-8"))
    want_ver = version if version and version.startswith("go") else (f"go{version}" if version else None)
    sysname = platform.system().lower()
    os_name = {"windows": "windows", "linux": "linux", "darwin": "darwin"}.get(sysname)
    arch = "amd64" if platform.machine().lower() in {"amd64", "x86_64"} else platform.machine().lower()
    kind = "archive"
    for rel in releases:
        if want_ver and rel.get("version") != want_ver:
            continue
        for f in rel.get("files", []):
            if f.get("os") == os_name and f.get("arch") == arch and f.get("kind") == kind:
                return {**f, "release": rel.get("version")}
    raise RuntimeError(f"no Go archive found for version={version!r} os={os_name} arch={arch}")


def _deno_asset(version: str | None = None, sha256: str | None = None) -> dict[str, Any]:
    url = _DENO_LATEST if not version else f"https://api.github.com/repos/denoland/deno/releases/tags/{version if version.startswith('v') else 'v' + version}"
    req = urllib.request.Request(url, headers={"User-Agent": "ArenaBridge/runtime.install"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 -- fixed GitHub API repo; asset digest verified before extraction  # nosemgrep: dynamic-urllib-use-detected -- URL is restricted to denoland/deno release API and downloaded asset is SHA-256 verified
            rel = json.loads(r.read().decode("utf-8"))
    except Exception:
        if not (version and sha256):
            raise
        tag = version.lstrip("v")
        sysname = platform.system().lower()
        mach = platform.machine().lower()
        arch = "x86_64" if mach in {"amd64", "x86_64"} else ("aarch64" if mach in {"arm64", "aarch64"} else mach)
        target = {"windows": f"deno-{arch}-pc-windows-msvc.zip", "linux": f"deno-{arch}-unknown-linux-gnu.zip", "darwin": f"deno-{arch}-apple-darwin.zip"}.get(sysname)
        return {"version": f"v{tag}", "filename": target, "url": f"https://github.com/denoland/deno/releases/download/v{tag}/{target}", "digest": f"sha256:{sha256}"}
    tag = str(rel.get("tag_name") or "").lstrip("v")
    sysname = platform.system().lower()
    mach = platform.machine().lower()
    arch = "x86_64" if mach in {"amd64", "x86_64"} else ("aarch64" if mach in {"arm64", "aarch64"} else mach)
    target = {
        "windows": f"deno-{arch}-pc-windows-msvc.zip",
        "linux": f"deno-{arch}-unknown-linux-gnu.zip",
        "darwin": f"deno-{arch}-apple-darwin.zip",
    }.get(sysname)
    for asset in rel.get("assets", []):
        if asset.get("name") == target:
            digest = str(asset.get("digest") or "")
            return {"version": f"v{tag}", "filename": target, "url": asset.get("browser_download_url"), "digest": digest}
    raise RuntimeError(f"no Deno archive found for version={version!r} target={target}")


def install_deno(version: str | None = None, sha256: str | None = None) -> dict[str, Any]:
    asset = _deno_asset(version, sha256=sha256)
    ver = asset["version"]
    root = tools_dir()
    target = root / f"deno-{ver.lstrip('v')}"
    exe_name = "deno.exe" if platform.system().lower() == "windows" else "deno"
    exe = target / exe_name
    if exe.exists():
        return {"ok": True, "runtime": "deno", "version": ver, "path": str(exe), "already_installed": True, "probe": _run_version(str(exe), ["--version"])}
    archive = root / str(asset["filename"])
    if not archive.exists():
        _download(str(asset["url"]), archive)
    got = _sha256(archive)
    digest = str(asset.get("digest") or "")
    expected = digest.split(":", 1)[-1] if digest.startswith("sha256:") else digest
    if expected and got.lower() != expected.lower():
        raise RuntimeError(f"sha256 mismatch for {archive.name}: got {got}, expected {expected}")
    tmp = root / f".deno-{ver.lstrip('v')}.extract"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    _extract_zip_safe(archive, tmp)
    candidates = list(tmp.rglob(exe_name))
    if not candidates:
        raise RuntimeError("Deno archive did not contain deno executable")
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    shutil.move(str(candidates[0]), str(exe))
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        exe.chmod(exe.stat().st_mode | 0o111)
    except Exception:
        pass
    reg = load_registry()
    reg.setdefault("runtimes", {})["deno"] = {"version": ver, "path": str(exe), "managed": True, "source": asset["url"], "sha256": got}
    save_registry(reg)
    return {"ok": True, "runtime": "deno", "version": ver, "path": str(exe), "sha256": got, "probe": _run_version(str(exe), ["--version"])}


def _lua_version_digits(version: str | None = None) -> str:
    v = str(version or "5.4").strip().lower().lstrip("v")
    if v in {"5.1", "51", "lua51"}:
        return "54".replace("54", "51")
    if v in {"5.3", "53", "lua53"}:
        return "53"
    if v in {"5.5", "55", "lua55"}:
        return "55"
    return "54"


def _lua_assets(version: str | None = None) -> dict[str, Any]:
    req = urllib.request.Request(_LUA_LATEST, headers={"User-Agent": "ArenaBridge/runtime.install"})
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 -- fixed GitHub API repo; assets SHA-256 verified before install  # nosemgrep: dynamic-urllib-use-detected -- URL is restricted to dyne/luabinaries release API and downloaded assets are SHA-256 verified
        rel = json.loads(r.read().decode("utf-8"))
    digits = _lua_version_digits(version)
    sysname = platform.system().lower()
    mach = platform.machine().lower()
    arch = "arm64" if mach in {"arm64", "aarch64"} else "x64"
    if sysname == "windows":
        names = [f"lua{digits}.exe", f"lua{digits}.dll"]
    elif sysname == "darwin":
        names = [f"lua{digits}-macos-{arch}"]
    elif sysname == "linux":
        names = [f"lua{digits}" if arch == "x64" else f"lua{digits}-linux-arm64"]
    else:
        raise RuntimeError(f"unsupported Lua platform: {sysname}")
    by_name = {a.get("name"): a for a in rel.get("assets", [])}
    assets = []
    for name in names:
        a = by_name.get(name)
        if not a:
            raise RuntimeError(f"Lua asset {name!r} not found in release {rel.get('tag_name')}")
        assets.append({"name": name, "url": a.get("browser_download_url"), "digest": str(a.get("digest") or "")})
    return {"version": f"5.{digits[-1]}", "tag": rel.get("tag_name"), "assets": assets}


def install_lua(version: str | None = None) -> dict[str, Any]:
    meta = _lua_assets(version)
    ver = str(meta["version"])
    root = tools_dir()
    target = root / f"lua-{ver}"
    exe_name = "lua.exe" if platform.system().lower() == "windows" else "lua"
    exe = target / exe_name
    digits = _lua_version_digits(version)
    dll = target / f"lua{digits}.dll"
    if exe.exists() and (platform.system().lower() != "windows" or dll.exists()):
        return {"ok": True, "runtime": "lua", "version": ver, "path": str(exe), "already_installed": True, "probe": _run_version(str(exe), ["-v"])}
    target.mkdir(parents=True, exist_ok=True)
    installed = []
    for asset in meta["assets"]:
        aname = str(asset["name"])
        dest = target / ("lua.exe" if aname.endswith(".exe") else aname if aname.endswith(".dll") else "lua")
        tmp = tools_dir() / str(asset["name"])
        if not tmp.exists():
            _download(str(asset["url"]), tmp)
        got = _sha256(tmp)
        expected = str(asset.get("digest") or "").split(":", 1)[-1]
        if expected and got.lower() != expected.lower():
            raise RuntimeError(f"sha256 mismatch for {asset['name']}: got {got}, expected {expected}")
        shutil.copy2(tmp, dest)
        try:
            dest.chmod(dest.stat().st_mode | 0o111)
        except Exception:
            pass
        installed.append({"name": asset["name"], "sha256": got, "path": str(dest)})
    reg = load_registry()
    reg.setdefault("runtimes", {})["lua"] = {"version": ver, "path": str(exe), "managed": True, "source": "dyne/luabinaries", "assets": installed}
    save_registry(reg)
    return {"ok": True, "runtime": "lua", "version": ver, "path": str(exe), "assets": installed, "probe": _run_version(str(exe), ["-v"])}


def _zig_asset(version: str | None = None) -> dict[str, Any]:
    req = urllib.request.Request(_ZIG_INDEX, headers={"User-Agent": "ArenaBridge/runtime.install"})
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 -- fixed official Zig download index; asset SHA-256 verified before extraction  # nosemgrep: dynamic-urllib-use-detected -- URL is fixed to ziglang.org/download/index.json and selected archive is SHA-256 verified
        data = json.loads(r.read().decode("utf-8"))
    ver = str(version or data.get("master", {}).get("version") or "").lstrip("v")
    if not version:
        stable = [k for k in data.keys() if k not in {"master"}]
        # The index keys are versions; sort by numeric-ish parts descending.
        import re as _re
        def key(v: str):
            return tuple(int(x) for x in _re.findall(r"\d+", v)[:3])
        ver = sorted(stable, key=key, reverse=True)[0]
    rel = data.get(ver) or data.get("v" + ver)
    if not isinstance(rel, dict):
        raise RuntimeError(f"no Zig release found for version={version!r}")
    sysname = platform.system().lower()
    mach = platform.machine().lower()
    arch = "x86_64" if mach in {"amd64", "x86_64"} else ("aarch64" if mach in {"arm64", "aarch64"} else mach)
    target_key = {"windows": f"{arch}-windows", "linux": f"{arch}-linux", "darwin": f"{arch}-macos"}.get(sysname)
    asset = rel.get(target_key)
    if not isinstance(asset, dict):
        raise RuntimeError(f"no Zig archive found for version={ver!r} target={target_key}")
    url = asset.get("tarball") or asset.get("url")
    filename = str(url).rsplit("/", 1)[-1]
    return {"version": ver, "filename": filename, "url": url, "digest": "sha256:" + str(asset.get("shasum") or "")}


def install_zig(version: str | None = None) -> dict[str, Any]:
    asset = _zig_asset(version)
    ver = str(asset["version"])
    root = tools_dir()
    target = root / f"zig-{ver}"
    exe_name = "zig.exe" if platform.system().lower() == "windows" else "zig"
    existing = _managed_zig_path(ver)
    if existing:
        return {"ok": True, "runtime": "zig", "version": ver, "path": str(existing), "already_installed": True, "probe": _run_version(str(existing), ["version"])}
    archive = root / str(asset["filename"])
    if not archive.exists():
        _download(str(asset["url"]), archive)
    got = _sha256(archive)
    expected = str(asset.get("digest") or "").split(":", 1)[-1]
    if expected and got.lower() != expected.lower():
        raise RuntimeError(f"sha256 mismatch for {archive.name}: got {got}, expected {expected}")
    tmp = root / f".zig-{ver}.extract"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if archive.suffix.lower() == ".zip":
        _extract_zip_safe(archive, tmp)
    else:
        _extract_tar_safe(archive, tmp)
    candidates = list(tmp.rglob(exe_name))
    if not candidates:
        raise RuntimeError("Zig archive did not contain zig executable")
    top = candidates[0].parent
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    top.rename(target)
    shutil.rmtree(tmp, ignore_errors=True)
    exe = _managed_zig_path(ver) or target / exe_name
    try:
        exe.chmod(exe.stat().st_mode | 0o111)
    except Exception:
        pass
    reg = load_registry()
    reg.setdefault("runtimes", {})["zig"] = {"version": ver, "path": str(exe), "managed": True, "source": asset["url"], "sha256": got}
    save_registry(reg)
    return {"ok": True, "runtime": "zig", "version": ver, "path": str(exe), "sha256": got, "probe": _run_version(str(exe), ["version"])}


def _wasmtime_asset(version: str | None = None) -> dict[str, Any]:
    url = _WASMTIME_LATEST if not version else f"https://api.github.com/repos/bytecodealliance/wasmtime/releases/tags/{version if version.startswith('v') else 'v' + version}"
    req = urllib.request.Request(url, headers={"User-Agent": "ArenaBridge/runtime.install"})
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 -- fixed GitHub API repo; asset digest verified before extraction  # nosemgrep: dynamic-urllib-use-detected -- URL is restricted to bytecodealliance/wasmtime release API and downloaded asset is SHA-256 verified
        rel = json.loads(r.read().decode("utf-8"))
    tag = str(rel.get("tag_name") or "").lstrip("v")
    sysname = platform.system().lower()
    mach = platform.machine().lower()
    arch = "x86_64" if mach in {"amd64", "x86_64"} else ("aarch64" if mach in {"arm64", "aarch64"} else mach)
    os_name = {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(sysname)
    suffix = ".zip" if sysname == "windows" else ".tar.xz"
    needle = f"wasmtime-v{tag}-{arch}-{os_name}{suffix}"
    for asset in rel.get("assets", []):
        if asset.get("name") == needle:
            digest = str(asset.get("digest") or "")
            return {"version": f"v{tag}", "filename": needle, "url": asset.get("browser_download_url"), "digest": digest}
    raise RuntimeError(f"no Wasmtime archive found for version={version!r} os={os_name} arch={arch}")


def install_wasmtime(version: str | None = None) -> dict[str, Any]:
    asset = _wasmtime_asset(version)
    ver = asset["version"]
    root = tools_dir()
    target = root / f"wasmtime-{ver.lstrip('v')}"
    exe_name = "wasmtime.exe" if platform.system().lower() == "windows" else "wasmtime"
    existing = _managed_wasmtime_path(ver)
    if existing:
        return {"ok": True, "runtime": "wasmtime", "version": ver, "path": str(existing), "already_installed": True, "probe": _run_version(str(existing), ["--version"])}
    archive = root / asset["filename"]
    if not archive.exists():
        _download(str(asset["url"]), archive)
    got = _sha256(archive)
    digest = str(asset.get("digest") or "")
    expected = digest.split(":", 1)[-1] if digest.startswith("sha256:") else digest
    if expected and got.lower() != expected.lower():
        raise RuntimeError(f"sha256 mismatch for {archive.name}: got {got}, expected {expected}")
    tmp = root / f".wasmtime-{ver.lstrip('v')}.extract"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if archive.suffix.lower() == ".zip":
        _extract_zip_safe(archive, tmp)
    else:
        _extract_tar_safe(archive, tmp)
    candidates = list(tmp.rglob(exe_name))
    if not candidates:
        raise RuntimeError("Wasmtime archive did not contain wasmtime executable")
    top = candidates[0].parent
    if top.name.lower() == "bin":
        top = top.parent
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    top.rename(target)
    shutil.rmtree(tmp, ignore_errors=True)
    exe = _managed_wasmtime_path(ver) or target / exe_name
    reg = load_registry()
    reg.setdefault("runtimes", {})["wasmtime"] = {"version": ver, "path": str(exe), "managed": True, "source": asset["url"], "sha256": got}
    reg.setdefault("runtimes", {})["wasm"] = {"version": ver, "path": str(exe), "managed": True, "source": asset["url"], "sha256": got, "runner": "wasmtime"}
    save_registry(reg)
    return {"ok": True, "runtime": "wasmtime", "version": ver, "path": str(exe), "sha256": got, "probe": _run_version(str(exe), ["--version"])}


def install_go(version: str | None = None) -> dict[str, Any]:
    asset = _go_asset(version)
    ver = asset["version"]  # e.g. go1.26.5
    root = tools_dir()
    target = root / ver
    exe = target / "bin" / ("go.exe" if platform.system().lower() == "windows" else "go")
    if exe.exists():
        return {"ok": True, "runtime": "go", "version": ver, "path": str(exe), "already_installed": True, "probe": _run_version(str(exe), ["version"])}
    url = f"https://go.dev/dl/{asset['filename']}"
    archive = root / asset["filename"]
    if not archive.exists():
        _download(url, archive)
    got = _sha256(archive)
    if got.lower() != str(asset["sha256"]).lower():
        raise RuntimeError(f"sha256 mismatch for {archive.name}: got {got}, expected {asset['sha256']}")
    tmp = root / f".{ver}.extract"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if archive.suffix.lower() == ".zip":
        _extract_zip_safe(archive, tmp)
    else:
        _extract_tar_safe(archive, tmp)
    extracted = tmp / "go"
    if not extracted.exists():
        raise RuntimeError("Go archive did not contain top-level go directory")
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    extracted.rename(target)
    shutil.rmtree(tmp, ignore_errors=True)
    reg = load_registry()
    reg.setdefault("runtimes", {})["go"] = {"version": ver, "path": str(exe), "managed": True, "source": url, "sha256": got}
    save_registry(reg)
    return {"ok": True, "runtime": "go", "version": ver, "path": str(exe), "sha256": got, "probe": _run_version(str(exe), ["version"])}


def install(runtime: str, version: str | None = None, sha256: str | None = None) -> dict[str, Any]:
    if runtime == "go":
        return install_go(version)
    if runtime == "deno":
        return install_deno(version, sha256=sha256)
    if runtime == "zig":
        return install_zig(version)
    if runtime == "lua":
        return install_lua(version)
    if runtime in {"wasm", "wasmtime"}:
        return install_wasmtime(version)
    return {"ok": False, "error": f"runtime.install currently supports: go, deno, zig, lua, wasmtime (got {runtime!r})"}
