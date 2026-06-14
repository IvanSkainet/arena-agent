"""Bridge bootstrap helpers: session env, config loading, port and logging."""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from collections.abc import Callable
from pathlib import Path


def ensure_session_env() -> None:
    """Ensure critical Linux desktop/session environment variables are present."""
    if os.name == "nt":
        return

    uid = os.getuid()

    if not os.environ.get("XDG_RUNTIME_DIR"):
        xdg = f"/run/user/{uid}"
        if os.path.isdir(xdg):
            os.environ["XDG_RUNTIME_DIR"] = xdg

    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        dbus_path = f"/run/user/{uid}/bus"
        if os.path.exists(dbus_path):
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_path}"

    if not os.environ.get("DISPLAY") and os.path.exists("/tmp/.X11-unix"):
        try:
            for xfile in os.listdir("/tmp/.X11-unix"):
                if xfile.startswith("X"):
                    os.environ["DISPLAY"] = f":{xfile[1:]}"
                    break
        except Exception:
            pass

    if not os.environ.get("WAYLAND_DISPLAY") and os.environ.get("XDG_RUNTIME_DIR"):
        wayland_sock = os.path.join(os.environ["XDG_RUNTIME_DIR"], "wayland-0")
        if os.path.exists(wayland_sock):
            os.environ["WAYLAND_DISPLAY"] = "wayland-0"


def load_config_file(
    *,
    log_info: Callable[..., None] | None = None,
    log_debug: Callable[..., None] | None = None,
    log_warning: Callable[..., None] | None = None,
) -> dict:
    """Load optional bridge.yml or bridge.json configuration file."""
    search_paths: list[Path] = []
    env_home = os.environ.get("ARENA_AGENT_HOME")
    if env_home:
        search_paths.append(Path(env_home) / "bridge.yml")
    search_paths.append(Path.home() / "arena-bridge" / "bridge.yml")
    search_paths.append(Path("bridge.yml"))

    for path in search_paths:
        if path.exists():
            try:
                import yaml
                with open(path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                if log_info:
                    log_info("[Config] Loaded configuration from %s", path)
                return cfg
            except ImportError:
                json_path = path.with_suffix(".json")
                if json_path.exists():
                    try:
                        with open(json_path, encoding="utf-8") as f:
                            cfg = json.load(f) or {}
                        if log_info:
                            log_info("[Config] Loaded JSON configuration from %s", json_path)
                        return cfg
                    except Exception:
                        pass
                if log_debug:
                    log_debug("[Config] bridge.yml found at %s but PyYAML not installed, skipping", path)
                return {}
            except Exception as e:
                if log_warning:
                    log_warning("[Config] Failed to load %s: %s", path, e)
                return {}
    return {}


def get_bridge_port() -> int:
    """Get the port the bridge is running on (from environment or default 8765)."""
    try:
        return int(os.environ.get("ARENA_PORT", "8765"))
    except (ValueError, TypeError):
        return 8765


def setup_logging(*, app_dir: Path, log_file: Path | None = None) -> logging.Logger:
    """Configure structured logging with file rotation and console output."""
    logger = logging.getLogger("arena-bridge")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    try:
        app_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            str(log_file or (app_dir / "bridge.log")),
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass

    return logger


def resolve_token(
    cli_token: str | None,
    *,
    default_token_file: Path,
    token_generator: Callable[[], str],
    log_info: Callable[..., None] | None = None,
) -> tuple[str, Path]:
    """Resolve auth token: CLI arg > env var > token file > auto-generate."""
    env_file = os.environ.get("ARENA_TOKEN_FILE")
    token_file = Path(env_file).expanduser() if env_file else default_token_file

    if cli_token:
        return cli_token, token_file

    env_tok = os.environ.get("ARENA_LOCAL_BRIDGE_TOKEN")
    if env_tok:
        return env_tok, token_file

    try:
        existing = token_file.read_text(encoding="utf-8").strip()
        if existing and len(existing) >= 16:
            return existing, token_file
    except FileNotFoundError:
        pass
    except Exception:
        pass

    new_tok = token_generator()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(new_tok + "\n", encoding="utf-8")
    try:
        os.chmod(token_file, 0o600)
    except Exception:
        pass
    if log_info:
        log_info("[ArenaBridge] New token generated and saved to %s", token_file)
    return new_tok, token_file


def daemonize(*, log_error: Callable[..., None] | None = None) -> None:
    """Double-fork to daemonize on Linux."""
    if os.name == "nt":
        return
    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError as e:
        if log_error:
            log_error("[ArenaBridge] First fork failed: %s", e)
        return

    os.setsid()
    os.umask(0)

    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError as e:
        if log_error:
            log_error("[ArenaBridge] Second fork failed: %s", e)
        return

    sys.stdout.flush()
    sys.stderr.flush()
    devnull_r = open(os.devnull, "r")
    os.dup2(devnull_r.fileno(), sys.stdin.fileno())
    devnull_r.close()
    devnull_w = open(os.devnull, "w")
    os.dup2(devnull_w.fileno(), sys.stdout.fileno())
    os.dup2(devnull_w.fileno(), sys.stderr.fileno())
    devnull_w.close()
