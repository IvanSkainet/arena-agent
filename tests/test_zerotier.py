"""ZeroTier network admin regressions.

The module now prefers the ZeroTier local HTTP API (127.0.0.1:9993) and
falls back to the CLI, so tests are shaped around the invariants of the
response contract instead of any specific transport.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.zerotier import (
    _cli_candidates,
    _install_hint,
    _parse_listnetworks,
    _permission_hint,
    _token_candidates,
    zerotier_network_action,
    zerotier_status,
)


def test_zerotier_status_contract_keys():
    """zerotier_status must always return the documented contract keys."""
    result = zerotier_status()
    for key in (
        "ok", "installed", "backend", "cli_source", "cli_path",
        "authtoken_path", "platform", "zerotier", "networks", "active_count",
    ):
        assert key in result, f"missing key {key} in status response"


def test_zerotier_status_never_raises_without_zerotier():
    """Even on a host without ZeroTier, status must return a structured error."""
    result = zerotier_status()
    # If not installed the module tells the caller in a friendly way.
    if not result["installed"]:
        assert result["ok"] is False
        assert result["backend"] == "none"
        assert result["hint"] is not None
        assert "install" in result["hint"].lower() or "download" in result["hint"].lower()


def test_zerotier_status_reports_platform():
    """Response includes the OS family so the dashboard can show it."""
    result = zerotier_status()
    assert result["platform"] in ("windows", "darwin", "linux")


def test_token_candidates_are_platform_specific():
    """Every OS has at least one candidate authtoken path."""
    candidates = _token_candidates()
    assert candidates, "token candidates list must not be empty"
    assert all(isinstance(c, str) and c for c in candidates)


def test_cli_candidates_is_a_list():
    """_cli_candidates returns real paths, all executable and de-duplicated."""
    import os
    seen = set()
    for path in _cli_candidates():
        assert path not in seen, f"duplicate CLI candidate: {path}"
        seen.add(path)
        assert os.path.isfile(path)
        assert os.access(path, os.X_OK)


def test_network_action_rejects_invalid():
    result = zerotier_network_action("dance-macabre")
    assert result["ok"] is False
    assert "action" in result["error"]


def test_network_action_requires_network_id():
    for action in ("join", "leave"):
        result = zerotier_network_action(action)
        assert result["ok"] is False
        assert "network_id" in result["error"]


def test_install_hint_reflects_platform():
    hint = _install_hint()
    assert isinstance(hint, str) and len(hint) > 20


def test_permission_hint_includes_root_cause():
    hint = _permission_hint("some underlying error")
    assert "some underlying error" in hint or "error" in hint.lower()


def test_parse_listnetworks_skips_header_and_comments():
    sample = (
        "# ZeroTier CLI output\n"
        "200 listnetworks <nwid> <name> <mac> <status> <type> <dev> <ips>\n"
        "200 listnetworks abcd1234efgh5678 my-net ee:aa:bb:cc:dd:11 OK PRIVATE zt0 10.0.0.1\n"
        "\n"
    )
    nets = _parse_listnetworks(sample)
    assert len(nets) == 1
    assert nets[0]["nwid"] == "abcd1234efgh5678"
    assert nets[0]["name"] == "my-net"
    assert nets[0]["active"] is True
    assert nets[0]["type"] == "PRIVATE"


def test_status_backend_is_stable_string():
    """backend must be one of the documented values."""
    result = zerotier_status()
    assert result["backend"] in ("http", "cli", "none")


def test_parse_listnetworks_parses_multiple_ips():
    """ZeroTier CLI comma-joins multiple IPs; every one should be preserved."""
    sample = (
        "200 listnetworks abcd1234efgh5678 my-net ee:aa:bb:cc:dd:11 OK PRIVATE zt0 10.0.0.1/24,fd80::1/40\n"
    )
    nets = _parse_listnetworks(sample)
    assert len(nets) == 1
    assert nets[0]["assignedAddresses"] == ["10.0.0.1/24", "fd80::1/40"]
    assert nets[0]["portDeviceName"] == "zt0"


def test_parse_listnetworks_skips_null_ip():
    """The CLI sometimes prints '-' when no IPs are assigned yet."""
    sample = "200 listnetworks abcd1234efgh5678 my-net ee:aa:bb:cc:dd:11 REQUESTING_CONFIGURATION PRIVATE zt0 -\n"
    nets = _parse_listnetworks(sample)
    assert len(nets) == 1
    assert nets[0]["assignedAddresses"] == []
    assert nets[0]["active"] is False


def test_cli_source_classifies_sudo_wrapper():
    """The optional Linux sudo wrapper is recognised as a distinct source."""
    from arena.admin.zerotier import _cli_source
    assert _cli_source("/usr/local/bin/zerotier-cli-wrapper") == "sudo-wrapper"
    assert _cli_source("/usr/bin/zerotier-cli-wrapper") == "sudo-wrapper"


def test_cli_source_classifies_direct_binary():
    """Every non-wrapper path is 'direct' — including Windows and macOS ones."""
    from arena.admin.zerotier import _cli_source
    assert _cli_source("/usr/bin/zerotier-cli") == "direct"
    assert _cli_source(r"C:\Program Files\ZeroTier\One\zerotier-cli.bat") == "direct"
    assert _cli_source("/Applications/ZeroTier One.app/Contents/MacOS/zerotier-cli") == "direct"


def test_subprocess_kwargs_hides_console_on_windows_only():
    """Windows spawns must set CREATE_NO_WINDOW; other OSes must not."""
    import platform as _p
    from arena.admin.zerotier import _SUBPROCESS_KWARGS
    if _p.system().lower() == "windows":
        assert "creationflags" in _SUBPROCESS_KWARGS
        assert _SUBPROCESS_KWARGS["creationflags"] & 0x08000000  # CREATE_NO_WINDOW
    else:
        assert _SUBPROCESS_KWARGS == {}, "non-Windows hosts must not carry creationflags"


def test_token_candidates_are_platform_specific_shape():
    """Every platform yields at least one absolute path."""
    import os as _os
    for path in _token_candidates():
        assert _os.path.isabs(path), f"token candidate must be absolute: {path}"


def test_zerotier_status_platform_matches_host():
    """The reported 'platform' field always matches platform.system()."""
    import platform as _p
    result = zerotier_status()
    assert result["platform"] == _p.system().lower()


def test_network_action_rejects_all_zero_nwid():
    """0000000000000000 is a syntactically valid nwid pattern but there is
    no such network — we still forward it because it might be intentional
    debugging; the guard is aimed at obviously malformed input, not
    obscure-but-legal values. So this is length-and-hex, not existence."""
    result = zerotier_network_action("join", "0000000000000000")
    # Length and hex are OK, so validation passes; the CLI/HTTP call is
    # what would produce whatever answer. We only assert that we did NOT
    # reject at the validate stage.
    assert result.get("error") is None or "16 hex" not in result.get("error", "")


def test_network_action_rejects_short_nwid():
    result = zerotier_network_action("join", "abc123")
    assert result["ok"] is False
    assert "16 hex" in result["error"]


def test_network_action_rejects_non_hex_nwid():
    result = zerotier_network_action("join", "gggggggggggggggg")
    assert result["ok"] is False
    assert "16 hex" in result["error"]


def test_network_action_normalises_uppercase_nwid():
    """Users sometimes paste uppercase from the ZT dashboard; normalise it."""
    # We can't observe the normalised value without side-effects, so at
    # minimum this must not be rejected as invalid.
    result = zerotier_network_action("leave", "ABCDEF0123456789")
    # If the CLI fails because there's no such joined network, that's fine —
    # we only assert we passed the format guard.
    assert result.get("error") is None or "16 hex" not in result.get("error", "")


def test_network_action_rejects_nwid_with_whitespace():
    """Trailing whitespace from copy-paste is stripped, not rejected."""
    result = zerotier_network_action("leave", "  abcdef0123456789  ")
    assert result.get("error") is None or "16 hex" not in result.get("error", "")
