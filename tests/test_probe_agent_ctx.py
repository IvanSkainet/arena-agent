"""Unit tests for arena/inventory/probe_agent_ctx.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _mod():
    """Return a namespace that unions probe_agent_ctx + probe_agent_sys
    so old tests that call m.get_dmesg_errors / m.get_virtualization
    keep working after the v3.88.5 module split."""
    for name in ("arena.inventory.probe_agent_ctx",
                 "arena.inventory.probe_agent_sys"):
        if name in sys.modules:
            del sys.modules[name]
    from arena.inventory import probe_agent_ctx, probe_agent_sys  # noqa: E402
    ns = SimpleNamespace()
    for src in (probe_agent_ctx, probe_agent_sys):
        for attr in dir(src):
            if not attr.startswith("_") or attr in ("_has_message_body",):
                setattr(ns, attr, getattr(src, attr))
    # Also expose the raw modules so patch.object(m.platform)-style
    # tests can find `platform`. Both files import the same one via
    # `from probe_common import *`; use ctx as the canonical.
    ns.platform = probe_agent_ctx.platform
    ns._which = probe_agent_ctx._which
    ns._run = probe_agent_ctx._run
    return ns


def test_all_probes_return_available_dict():
    m = _mod()
    for fn_name in ("get_python_venvs", "get_git_repos",
                    "get_env_secret_names", "get_crontab_entries",
                    "get_dns_resolvers", "get_dmesg_errors",
                    "get_journal_errors", "get_virtualization",
                    "get_time_sync", "get_firewall_status"):
        r = getattr(m, fn_name)()
        assert isinstance(r, dict), fn_name
        assert "available" in r and isinstance(r["available"], bool), fn_name


def test_env_secret_names_returns_names_only_never_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-XXXX-supersecret-XXXX")
    monkeypatch.setenv("MY_TOKEN", "actual-token-value-1234")
    monkeypatch.setenv("DB_PASSWORD", "hunter2")
    monkeypatch.setenv("FOO", "plain")
    m = _mod()
    r = m.get_env_secret_names()
    assert r["available"] is True
    assert "OPENAI_API_KEY" in r["names"]
    assert "MY_TOKEN" in r["names"]
    assert "DB_PASSWORD" in r["names"]
    assert "FOO" not in r["names"]
    # CRITICAL: value must never appear anywhere in the dict.
    serialized = repr(r)
    assert "sk-XXXX-supersecret-XXXX" not in serialized
    assert "actual-token-value-1234" not in serialized
    assert "hunter2" not in serialized


def test_env_secret_names_ignores_path_and_similar():
    m = _mod()
    r = m.get_env_secret_names()
    # PATH must not be classified as a secret even though it contains
    # the substring "PATH" (which doesn't match any marker anyway).
    # SSH_AUTH_SOCK is on the allowlist.
    assert "PATH" not in r["names"]
    assert "SSH_AUTH_SOCK" not in r["names"]
    assert "PYTHONPATH" not in r["names"]


def test_env_secret_names_no_false_positives_on_session_and_desktop(monkeypatch):
    """v3.88.4: SESSION as a marker was matching DBUS_SESSION_BUS_ADDRESS,
    DESKTOP_SESSION, XDG_SESSION_*. Those aren't credentials -- they
    were noise. Confirm they don't appear in the credential list."""
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setenv("DESKTOP_SESSION", "plasma")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("ICEAUTHORITY", "/tmp/.ICEauth")
    m = _mod()
    r = m.get_env_secret_names()
    for false_positive in ("DBUS_SESSION_BUS_ADDRESS", "DESKTOP_SESSION",
                           "XDG_SESSION_TYPE", "ICEAUTHORITY"):
        assert false_positive not in r["names"], (
            f"'{false_positive}' incorrectly classified as a credential"
        )


def test_env_secret_names_splits_file_refs_from_credentials(monkeypatch):
    """v3.88.4: OPENAI_API_KEY is a real credential env; ARENA_TOKEN_FILE
    is a filesystem path. Both interesting to the agent, but different
    categories."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("ARENA_TOKEN_FILE", "/etc/arena/token.txt")
    monkeypatch.setenv("HF_TOKEN_FILE", "/etc/hf-token.txt")
    m = _mod()
    r = m.get_env_secret_names()
    assert "OPENAI_API_KEY" in r["names"]
    assert "ARENA_TOKEN_FILE" in r["file_refs"]
    assert "HF_TOKEN_FILE" in r["file_refs"]
    # And they must NOT be in the other list.
    assert "ARENA_TOKEN_FILE" not in r["names"]
    assert "OPENAI_API_KEY" not in r["file_refs"]


def test_python_venvs_detects_venv(tmp_path):
    m = _mod()
    venv = tmp_path / "myenv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12.1\n")
    bin_dir = venv / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").touch()
    r = m.get_python_venvs(scan_root=str(tmp_path))
    assert r["available"] is True
    assert any(v["path"] == str(venv) for v in r["venvs"])
    assert any(v.get("python_version") == "3.12.1" for v in r["venvs"])


def test_python_venvs_empty_dir():
    m = _mod()
    r = m.get_python_venvs(scan_root="/nonexistent-arena-scan-root")
    assert r["available"] is False


def test_virtualization_returns_type():
    m = _mod()
    r = m.get_virtualization()
    # Just needs to return a plausible dict with the type key.
    if r["available"]:
        assert r["type"] in ("bare-metal", "vm", "container", "unknown")


def test_dmesg_off_linux():
    m = _mod()
    # dmesg lives in probe_agent_sys after the v3.88.5 split.
    from arena.inventory import probe_agent_sys as sys_mod
    with patch.object(sys_mod, "platform") as pm:
        pm.system.return_value = "Windows"
        r = sys_mod.get_dmesg_errors()
    assert r["available"] is False
    assert "linux" in r["error"].lower()


def test_firewall_status_reports_backend_or_missing():
    m = _mod()
    r = m.get_firewall_status()
    if r["available"]:
        assert r["backend"] in (
            "ufw", "firewalld", "nftables", "iptables",
            "pf/alf", "windows-defender-firewall",
        )
    else:
        assert r.get("error"), "firewall probe must include error when unavailable"


def test_dns_resolvers_returns_nameservers_list():
    m = _mod()
    r = m.get_dns_resolvers()
    if r["available"]:
        assert isinstance(r.get("nameservers", []), list)


def test_git_repos_handles_no_git_binary():
    _mod()
    from arena.inventory import probe_agent_ctx as ctx_mod
    with patch.object(ctx_mod, "_which", return_value=None):
        r = ctx_mod.get_git_repos()
    assert r["available"] is False
    assert "git" in r["error"].lower()


def test_sections_include_v884_probes():
    from arena.inventory.report import SECTIONS
    names = [name for name, _ in SECTIONS]
    for expected in ("python_venvs", "git_repos", "env_secret_names",
                     "crontab_entries", "dns_resolvers", "dmesg_errors",
                     "journal_errors", "virtualization", "time_sync",
                     "firewall_status"):
        assert expected in names, f"SECTIONS missing '{expected}'"


def test_hardware_normalize_exposes_v884_fields():
    from arena.inventory.hardware import normalize_inventory_hardware
    inv = {
        "python_venvs": {"available": True, "venvs": [{"path": "/a"}]},
        "git_repos":    {"available": True, "repos": [{"path": "/b"}]},
        "env_secret_names": {"available": True, "names": ["FOO_TOKEN"], "file_refs": []},
        "virtualization": {"available": True, "type": "bare-metal"},
        "time_sync": {"available": True, "server": "pool.ntp.org"},
        "firewall_status": {"available": True, "backend": "ufw"},
    }
    hw = normalize_inventory_hardware(inv)
    for key in ("python_venvs", "git_repos", "env_secret_names",
                "virtualization", "time_sync", "firewall_status",
                "dns_resolvers", "crontab_entries", "dmesg_errors",
                "journal_errors"):
        assert key in hw, f"/v1/hardware missing '{key}'"


def test_text_format_shows_full_service_list_not_and_more():
    """v3.88.4 regression guard: text_format used to print
    'and 33 more' for long service lists. Must show all of them.
    """
    from arena.inventory.text_format import format_text
    data = {
        "services": {"systemd_user_running": [f"svc-{i}.service" for i in range(50)]},
    }
    out = format_text(data)
    assert "and 33 more" not in out
    assert "and 40 more" not in out
    assert "svc-49.service" in out


def test_text_format_kernel_modules_header_matches_shown():
    from arena.inventory.text_format import format_text
    data = {
        "kernel_modules": {
            "available": True,
            "count": 156,
            "modules": [{"name": f"m{i}", "size_bytes": 1000 - i,
                          "used_count": 0, "used_by": []} for i in range(156)],
        },
    }
    out = format_text(data)
    # v3.88.3 said "showing top 156" but only rendered 15. v3.88.4
    # header must match reality.
    assert "showing top 15" in out
    assert "showing top 156" not in out


def test_text_format_screens_no_json_dump():
    """v3.88.4 regression guard: screens were printed as raw JSON."""
    from arena.inventory.text_format import format_text
    data = {
        "displays": {
            "XDG_SESSION_TYPE": "wayland",
            "screens": [{"output": "DP-1", "geometry": "2560x1440+0+0"}],
        },
    }
    out = format_text(data)
    # Must not contain "{" or the raw dict repr for the screen block.
    for line in out.splitlines():
        if line.strip().startswith("screen"):
            assert "{" not in line, f"screen line contains raw JSON: {line}"
            assert "DP-1" in line


# ---------- v3.88.5 fixes -------------------------------------------------

def test_git_repos_dedupes_symlinked_paths(tmp_path):
    """v3.88.5: ~/cwd -> ~/arena-bridge symlinks should NOT create a
    duplicate git repo entry. And a repo under a bind mount should
    only appear once."""
    m = _mod()
    real_repo = tmp_path / "real_repo"
    real_repo.mkdir()
    (real_repo / ".git").mkdir()
    # Symlink to the same repo
    symlink = tmp_path / "cwd_link"
    try:
        symlink.symlink_to(real_repo)
    except (OSError, NotImplementedError):
        # Windows without dev-mode: skip
        return
    r = m.get_git_repos(scan_root=str(tmp_path))
    paths_resolved = [str(__import__("pathlib").Path(p["path"]).resolve())
                      for p in r["repos"]]
    # Only one entry, and it points at the real repo.
    assert len(paths_resolved) == 1, (
        f"Expected 1 repo, got {len(paths_resolved)}: {paths_resolved}"
    )


def test_dmesg_filters_empty_message_bodies():
    """v3.88.5: lines like '... cachyos-x8664 kernel:' with an empty
    body must not appear in the errors list."""
    from arena.inventory.probe_agent_sys import _has_message_body
    assert _has_message_body("2026-07-16T01:38:10+05:00 cachyos-x8664 kernel: TDX not supported")
    assert not _has_message_body("2026-07-16T01:38:10+05:00 cachyos-x8664 kernel:")
    assert not _has_message_body("2026-07-16T06:18:11+05:00 cachyos-x8664 kernel: ")
    assert _has_message_body("systemd[1]: Started foo.service")
    assert not _has_message_body("systemd[1]: ")
    # Non-log lines pass through (defensive default).
    assert _has_message_body("some plain message")
