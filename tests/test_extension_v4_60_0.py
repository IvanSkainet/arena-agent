"""v4.60.0 — Windows/dashboard fixes: hooks emoji + ZT transports + session state."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from arena import constants


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(p: str) -> str:
    return (REPO_ROOT / p).read_text(encoding="utf-8")


def test_version_is_4_60_0():
    assert constants.VERSION in ("4.60.0", "4.60.1", "4.60.2", "4.60.3", "4.60.4", "4.60.5", "4.60.6")


def test_pyproject_version_is_4_60_0():
    assert any(v in _read("pyproject.toml") for v in ('version = "4.60.0"', 'version = "4.60.1"', 'version = "4.60.2"', 'version = "4.60.3"', 'version = "4.60.4"', 'version = "4.60.5"', 'version = "4.60.6"'))


# ------------------------------------------------------------------
# #7 — Hooks emoji: never use Emoji 14.0 code points in tabs registry
# because Windows 10 LTSC 2021 base Segoe UI Emoji is Emoji 13.1 max.
# ------------------------------------------------------------------
def test_tabs_registry_avoids_emoji_14():
    """Emoji 14.0 additions (Sept 2021) are not in Windows 10 LTSC 2021
    base fonts. Guard against re-introducing them silently.

    The Emoji 14.0 additions include U+1FA9D 🪝 (hook), U+1FAAA 🪪 (id-card),
    U+1FAB7 🪷 (lotus), U+1FAC3 🫃 (pregnant man), etc. We block just the
    small set actually tempting for UI icons.
    """
    forbidden = {
        "\U0001FA9D": "🪝 (hook, Emoji 14) — use 🎣 U+1F3A3",
        "\U0001FA84": "🪄 (magic wand, Emoji 13.1) — Windows 10 LTSC base doesn't ship it",
        "\U0001FAA9": "🪩 (mirror ball, Emoji 14)",
    }
    src = _read("dashboard/assets/00-tabs-registry.js")
    # Only inspect the icon strings, not comments
    icons = re.findall(r'icon:\s*"([^"]+)"', src)
    joined = "".join(icons)
    for ch, reason in forbidden.items():
        assert ch not in joined, f"tabs registry uses forbidden emoji {reason}"


def test_hooks_uses_fishing_pole_emoji():
    src = _read("dashboard/assets/00-tabs-registry.js")
    m = re.search(r'{name:\s*"hooks"[^}]*icon:\s*"([^"]+)"', src)
    assert m, "hooks tab entry not found"
    assert m.group(1) == "\U0001F3A3", f"hooks emoji should be 🎣 U+1F3A3, got U+{ord(m.group(1)):X}"


# ------------------------------------------------------------------
# #2 — Transports ZT snapshot uses the actual field from zerotier_status
# ------------------------------------------------------------------
def test_transports_zt_uses_installed_field():
    """Prior to v4.60.0, transports.js checked `ztRaw.available !== false`
    but zerotier_status() returns `installed` (not `available`). Result:
    ZT always shown as installed even on hosts without it."""
    src = _read("dashboard/assets/20-transports.js")
    # Must use ztRaw.installed
    assert "installed: ztRaw.installed" in src, "must consult ztRaw.installed"
    # Must NOT check ztRaw.available in actual code (phantom field).
    # Comments referring to the old bug are fine — inspect only non-comment lines.
    code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("//")]
    joined = "\n".join(code_lines)
    assert "ztRaw.available" not in joined, "ztRaw.available in real code path"


def test_transports_zt_active_considers_active_count():
    """CLI backend doesn't populate zerotier.online. active_count > 0 is
    a stronger signal that the daemon is actually connected to a network."""
    src = _read("dashboard/assets/20-transports.js")
    assert "active_count" in src


# ------------------------------------------------------------------
# Session state (foundation for bug #9) — checkpoint file schema
# ------------------------------------------------------------------
def test_agent_session_module_exists():
    from arena import agent_session  # noqa: F401


def test_session_write_read_roundtrip(tmp_path, monkeypatch):
    from arena.agent_session import write_checkpoint, read_checkpoint
    monkeypatch.setenv("ARENA_AGENT_SESSION_FILE", str(tmp_path / "sess.json"))
    write_checkpoint({
        "goal": "reproduce phone-voice-to-chat",
        "current_step": "waiting on Ivan's Windows",
        "release": "v4.60.0",
        "notes": ["one", "two"],
    })
    got = read_checkpoint()
    assert got["goal"] == "reproduce phone-voice-to-chat"
    assert got["release"] == "v4.60.0"
    assert got["updated_at"]  # auto-stamped


def test_session_read_missing_returns_none(tmp_path, monkeypatch):
    from arena.agent_session import read_checkpoint
    monkeypatch.setenv("ARENA_AGENT_SESSION_FILE", str(tmp_path / "nope.json"))
    assert read_checkpoint() is None


def test_session_append_note(tmp_path, monkeypatch):
    from arena.agent_session import write_checkpoint, append_note, read_checkpoint
    monkeypatch.setenv("ARENA_AGENT_SESSION_FILE", str(tmp_path / "s.json"))
    write_checkpoint({"goal": "x", "notes": []})
    append_note("first observation")
    append_note("second observation")
    got = read_checkpoint()
    assert got["notes"] == ["first observation", "second observation"]


def test_session_default_path_under_home(monkeypatch):
    monkeypatch.delenv("ARENA_AGENT_SESSION_FILE", raising=False)
    from arena.agent_session import _session_path
    p = _session_path()
    assert p.name == "agent_session.json"
    assert ".arena" in str(p)


# ------------------------------------------------------------------
# Changelog
# ------------------------------------------------------------------
def test_changelog_mentions_v4_60_0():
    assert "4.60.0" in _read("CHANGELOG.md")
    assert "4.60.0" in _read("CHANGELOG.ru.md")
