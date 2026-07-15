"""Extended context probes for AI agents (v3.88.4).

Additions on top of probe_agent_facts.py:
    * python_venvs         -- discovered virtualenvs (~/.local + $HOME) with
                              their Python version and top packages.
    * git_repos            -- all .git repos under $HOME with branch,
                              dirty-file count, ahead/behind, last commit.
    * env_secret_names     -- NAMES only of env vars that look like secrets
                              (never the values). Agent knows what auth is
                              configured without leaking anything.
    * crontab_entries      -- user + system cron jobs (Linux/macOS).
    * dns_resolvers        -- /etc/resolv.conf + hosts + mDNS state.
    * dmesg_errors         -- recent kernel-level errors (Linux).
    * journal_errors       -- recent systemd service errors (Linux).
    * virtualization       -- bare-metal / VM / container / WSL2 detection.
    * time_sync            -- NTP status, offset, drift, source.
    * firewall_status      -- active firewall backend + rule count summary.

Same contract as probe_agent_facts.py: every probe returns
``{"available": bool, ...}``, never raises, degrades cleanly.
"""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403


# ------------------------------------------------------------------ python_venvs

def get_python_venvs(scan_root: str | None = None, limit: int = 15) -> dict:
    """Find virtualenvs under $HOME and report each one's Python version
    and top-installed packages. Agents use this to spot existing envs
    instead of creating a new one for every task.
    """
    info: dict[str, Any] = {"available": False, "venvs": []}
    home = Path(scan_root or os.path.expanduser("~"))
    if not home.exists():
        info["error"] = "$HOME not accessible"
        return info

    # A directory is a venv if it contains ``bin/activate`` (POSIX) or
    # ``Scripts\activate.bat`` (Windows) AND a ``pyvenv.cfg`` next to
    # them. We stop at depth 5 so we don't crawl node_modules for an hour.
    seen: set[str] = set()

    def _is_venv(p: Path) -> bool:
        return (p / "pyvenv.cfg").is_file() and (
            (p / "bin" / "python").exists()
            or (p / "bin" / "python3").exists()
            or (p / "Scripts" / "python.exe").exists()
        )

    def _walk(root: Path, depth: int = 0) -> None:
        if depth > 5 or len(info["venvs"]) >= limit:
            return
        try:
            entries = list(root.iterdir())
        except (PermissionError, OSError):
            return
        for e in entries:
            if not e.is_dir():
                continue
            # Skip trash directories that never contain a venv.
            if e.name in ("node_modules", ".cache", ".git",
                          "__pycache__", "target", "dist", "build"):
                continue
            if e.is_symlink():
                continue
            try:
                key = str(e.resolve())
            except (OSError, RuntimeError):
                key = str(e)
            if key in seen:
                continue
            seen.add(key)
            if _is_venv(e):
                _record_venv(e, info["venvs"])
                if len(info["venvs"]) >= limit:
                    return
                continue
            _walk(e, depth + 1)

    _walk(home)
    info["available"] = bool(info["venvs"])
    info["scanned_root"] = str(home)
    return info


def _record_venv(path: Path, out: list[dict]) -> None:
    entry: dict[str, Any] = {"path": str(path)}
    cfg = path / "pyvenv.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            k, _, v = line.partition("=")
            k = k.strip().lower()
            v = v.strip()
            if k == "version":
                entry["python_version"] = v
            elif k == "prompt":
                entry["prompt"] = v
    except Exception:
        pass
    # Package count from lib/python*/site-packages/*.dist-info
    pkgs = 0
    for sp in list(path.rglob("site-packages"))[:2]:
        try:
            pkgs += sum(1 for _ in sp.glob("*.dist-info"))
        except Exception:
            pass
    entry["package_count"] = pkgs
    out.append(entry)


# ------------------------------------------------------------------ git_repos

def get_git_repos(scan_root: str | None = None, limit: int = 30) -> dict:
    """All .git repos under $HOME with branch / dirty / ahead-behind /
    last commit. Agents doing project work check that nothing is
    uncommitted before mass edits.
    """
    info: dict[str, Any] = {"available": False, "repos": []}
    if not _which("git"):
        info["error"] = "git not on PATH"
        return info
    home = Path(scan_root or os.path.expanduser("~"))
    if not home.exists():
        info["error"] = "$HOME not accessible"
        return info

    # De-duplication uses resolved (symlink-followed) paths. Without
    # this, symlinks like ~/cwd -> ~/arena-bridge and bind-mount
    # duplicates (subvolumes, docker overlays) produce N copies of
    # the same repo. We keep the FIRST discovered path as the display
    # name so cosmetic paths (~/projects/foo) still win over
    # backing-store paths (/var/mnt/.../foo).
    seen_real: set[str] = set()
    found: list[Path] = []

    def _walk(root: Path, depth: int = 0) -> None:
        if depth > 5 or len(found) >= limit:
            return
        try:
            entries = list(root.iterdir())
        except (PermissionError, OSError):
            return
        for e in entries:
            if not e.is_dir():
                continue
            if e.name in ("node_modules", ".cache", "__pycache__",
                          "target", "dist", "build", "venv", ".venv"):
                continue
            if e.is_symlink():
                # Symlinks to directories cause duplicate discovery
                # (~/cwd -> ~/arena-bridge). Skip them entirely --
                # the real path is walked separately.
                continue
            if (e / ".git").exists():
                try:
                    real = str(e.resolve())
                except (OSError, RuntimeError):
                    real = str(e)
                if real in seen_real:
                    continue
                seen_real.add(real)
                found.append(e)
                # Do NOT recurse into a repo's subdirs; agents don't
                # need to see git-submodules as separate top-level entries.
                continue
            _walk(e, depth + 1)

    _walk(home)

    for repo in found[:limit]:
        entry: dict[str, Any] = {"path": str(repo)}
        # Cheap ops: branch, status --porcelain, remote tracking.
        try:
            entry["branch"] = _run(
                ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                timeout=3,
            ).strip() or None
        except Exception:
            entry["branch"] = None
        try:
            porcelain = _run(
                ["git", "-C", str(repo), "status", "--porcelain"], timeout=3,
            )
            entry["dirty_files"] = sum(1 for ln in porcelain.splitlines() if ln.strip())
        except Exception:
            entry["dirty_files"] = None
        try:
            ab = _run(
                ["git", "-C", str(repo), "rev-list", "--left-right", "--count",
                 "HEAD...@{u}"], timeout=3,
            ).split()
            if len(ab) == 2:
                entry["ahead"] = int(ab[0])
                entry["behind"] = int(ab[1])
        except Exception:
            pass
        try:
            entry["last_commit"] = _run(
                ["git", "-C", str(repo), "log", "-1",
                 "--format=%h %ai %s"], timeout=3,
            ).strip()[:120]
        except Exception:
            pass
        info["repos"].append(entry)

    info["available"] = bool(info["repos"])
    info["scanned_root"] = str(home)
    return info


# ------------------------------------------------------------------ env_secret_names

# Substrings that mark an env var as sensitive. Names only ever leave
# the process; VALUES stay in the process memory. Case-insensitive.
# SESSION was too greedy (matched DBUS_SESSION_BUS_ADDRESS,
# DESKTOP_SESSION, XDG_SESSION_*) so it's out; API_KEY / TOKEN /
# SECRET / PASSWORD / etc. catch actual credentials without those
# false positives.
_SECRET_MARKERS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL",
    "API_KEY", "APIKEY", "PRIVATE_KEY", "PASSPHRASE",
    "AUTH_TOKEN", "ACCESS_KEY", "SECRET_KEY", "SECRET_ACCESS_KEY",
    "COOKIE_SECRET", "SESSION_SECRET", "SIGNING_KEY", "SIGNING_SECRET",
    "OAUTH", "BEARER", "JWT_SECRET", "DATABASE_URL", "DB_URL",
)
# Names that MATCH _SECRET_MARKERS but are almost never secrets and just
# clutter the output. Path-y things like *_TOKEN_FILE / *_KEY_FILE are
# filenames, not the secret itself -- an agent still wants to know the
# NAME to look up the file's role, but they're not secrets in the
# leak-sensitive sense.
_SECRET_ALLOWLIST = (
    "PATH", "PWD", "OLDPWD", "SSH_AUTH_SOCK", "PYTHONPATH", "MANPATH",
    "LD_LIBRARY_PATH", "XDG_RUNTIME_DIR",
)
# Any name that ends in _FILE / _PATH is a path to something, not the
# secret. Report it in a separate list so agents still know the file
# is configured, but don't confuse it with the actual credential env.
_SECRET_FILE_SUFFIXES = ("_FILE", "_PATH")


def get_env_secret_names() -> dict:
    """List env var NAMES that look like credentials. Never values.

    Values would be a security incident waiting to happen; this probe
    exists so agents can plan around available auth ("OpenAI key is
    configured, use direct API"; "no HF token, use a local model")
    without ever seeing the actual secret.

    Returns three lists so the agent can distinguish:
        * `names`      -- names that most likely hold the credential
                          directly (OPENAI_API_KEY, MY_TOKEN, ...).
        * `file_refs`  -- names ending in _FILE / _PATH that point to
                          the credential on disk (ARENA_TOKEN_FILE,
                          GOOGLE_APPLICATION_CREDENTIALS, ...).
        * `count`      -- convenience: len(names).
    """
    info: dict[str, Any] = {"available": False, "names": [],
                             "file_refs": [], "count": 0}
    for name in sorted(os.environ.keys()):
        upper = name.upper()
        if upper in _SECRET_ALLOWLIST:
            continue
        if not any(m in upper for m in _SECRET_MARKERS):
            continue
        if any(upper.endswith(sfx) for sfx in _SECRET_FILE_SUFFIXES):
            info["file_refs"].append(name)
        else:
            info["names"].append(name)
    info["count"] = len(info["names"])
    info["available"] = True
    return info


# ------------------------------------------------------------------ crontab_entries

def get_crontab_entries() -> dict:
    """User crontab + /etc/cron.* system entries (Linux/macOS).

    Agents scheduling their own work should know what's already on
    the schedule so they don't clash with an nightly build at 03:00.
    """
    info: dict[str, Any] = {"available": False,
                             "user_entries": [], "system_entries": []}
    sys_name = platform.system()
    if sys_name not in ("Linux", "Darwin"):
        info["error"] = "cron is POSIX-only"
        return info

    if _which("crontab"):
        out = _run(["crontab", "-l"], timeout=3)
        for ln in out.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            info["user_entries"].append(ln[:180])

    # System cron: /etc/cron.d/*, /etc/crontab, /etc/cron.{hourly,daily,...}
    for candidate in [Path("/etc/crontab")] + list(Path("/etc/cron.d").glob("*") if Path("/etc/cron.d").exists() else []):
        try:
            if not candidate.is_file():
                continue
            for ln in candidate.read_text(encoding="utf-8",
                                           errors="replace").splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                info["system_entries"].append(f"{candidate.name}: {ln[:160]}")
        except Exception:
            continue
    for period in ("hourly", "daily", "weekly", "monthly"):
        d = Path(f"/etc/cron.{period}")
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file():
                    info["system_entries"].append(f"{period}: {f.name}")

    info["available"] = True
    return info


