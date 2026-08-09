"""v4.169.14 -- reachability, and the checks that were red for no reason.

Three defects the phone surfaced, all of the same family: a report that
does not distinguish "broken" from "not applicable here".

1. **No way to reach the phone.** The bridge binds `127.0.0.1`, so after
   a reboot -- which also switched wireless ADB back off -- nothing could
   connect from anywhere, and nothing on the phone said so. `/v1/access`
   answers the question directly, and `loopback_only` is published on the
   unauthenticated `/v1/version` because the Android app cannot hold the
   token: it lives inside Termux's private tree.

2. **"Missions dir" red on a fresh install.** A runtime directory that
   has never been used does not exist yet. That is not a fault, and a
   permanently red light teaches the operator to ignore red lights.

3. **"Sound: no sound device" red on every phone.** Android has neither
   ALSA nor PulseAudio, so `paplay`/`beep` can never be present. The
   check was reporting a property of the platform as a defect.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from arena.mobile import access_info

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- /v1/access ------------------------------------------------------------

def test_a_tunnel_reaches_a_loopback_bridge() -> None:
    """Caught by using the endpoint on the PC, over ngrok, while it said
    the opposite.

    The first version claimed a loopback bind was unreachable "not even
    through a tunnel" -- and the response saying so arrived through a
    tunnel. A tunnel agent runs on the same host and dials 127.0.0.1
    itself; loopback blocks direct LAN access, not local forwarders.
    """
    info = access_info.describe(
        bind="127.0.0.1", port=8765,
        tunnels={"ngrok": {"active": True, "public_url": "https://x.ngrok.dev"}},
    )
    assert info["loopback_only"] is True
    assert info["reachable_remotely"] is True, "the tunnel does forward"
    assert info["reachable_on_lan"] is False, "but no other machine connects directly"
    assert info["lan_urls"] == []
    assert "tunnel forwards" in info["why"]


def test_loopback_without_a_tunnel_is_unreachable() -> None:
    info = access_info.describe(bind="127.0.0.1", port=8765, tunnels={})
    assert info["reachable_remotely"] is False
    assert info["reachable_on_lan"] is False
    assert "no other machine can connect directly" in info["why"]


def test_open_bind_with_a_tunnel_is_reachable() -> None:
    with patch.object(access_info, "local_addresses",
                      return_value=[{"address": "192.168.1.5", "kind": "lan"}]):
        info = access_info.describe(
            bind="0.0.0.0", port=8765,
            tunnels={"ngrok": {"active": True, "public_url": "https://x.ngrok.dev"}},
        )
    assert info["reachable_remotely"] is True
    assert info["lan_urls"] == ["http://192.168.1.5:8765"]
    assert info["tunnel_urls"] == ["https://x.ngrok.dev"]


def test_open_bind_without_a_tunnel_is_lan_only() -> None:
    """Two different claims, kept apart."""
    with patch.object(access_info, "local_addresses",
                      return_value=[{"address": "192.168.1.5", "kind": "lan"}]):
        info = access_info.describe(bind="0.0.0.0", port=8765, tunnels={})
    assert info["reachable_on_lan"] is True
    assert info["reachable_remotely"] is False


def test_every_loopback_spelling_counts() -> None:
    for bind in ("127.0.0.1", "localhost", "::1", "", "127.0.0.5"):
        info = access_info.describe(bind=bind, port=8765)
        assert info["loopback_only"] is True, bind


def test_tailnet_addresses_are_labelled_separately_from_lan() -> None:
    """A LAN address dies when the phone leaves the house."""
    assert access_info._classify("100.90.1.2") == "tailnet"
    assert access_info._classify("192.168.1.5") == "lan"
    assert access_info._classify("8.8.8.8") == "public"


# --- doctor ----------------------------------------------------------------

def _doctor(**kw):
    from arena.system import doctor
    base = dict(
        version="4.169.14", token="t" * 32,
        bridge_dir=Path("/tmp"),
        memory_dir=Path("/tmp/definitely-not-created-memory"),
        missions_dir=Path("/tmp/definitely-not-created-missions"),
        facts_count_fn=lambda: 0,
        internet_check_fn=lambda: True,
    )
    base.update(kw)
    return {c["name"]: c for c in doctor.run_doctor(**base)["checks"]}


def test_unused_runtime_dirs_are_empty_not_broken() -> None:
    checks = _doctor()
    for name in ("Missions dir", "Memory dir"):
        assert checks[name]["ok"] is True, f"{name} red on a fresh install"
        assert checks[name]["status"] == "empty"
        assert checks[name]["critical"] is False
        assert "not created yet" in checks[name]["detail"]


def test_a_missing_bridge_dir_is_still_a_real_failure() -> None:
    """The installer creates it, so its absence genuinely is broken."""
    checks = _doctor(bridge_dir=Path("/tmp/definitely-not-a-bridge-dir"))
    assert checks["Bridge dir"]["ok"] is False


def test_sound_is_not_a_failure_on_android() -> None:
    """Android has no ALSA, so paplay/beep can never be there.

    `sys.platform` is faked as well as the host class: on a Windows
    runner the doctor takes the winsound branch long before it asks
    whether this is Android, so a test that only patched is_android
    passed on Linux and failed on all five Windows jobs. Same shape as
    v4.169.9 -- a platform assumption baked into a test.
    """
    with patch("arena.system.doctor.sys.platform", "linux"), \
         patch("arena.hostplatform.is_android", return_value=True):
        checks = _doctor()
    sound = checks["Sound"]
    assert sound["ok"] is True, "every Android phone would be permanently red"
    assert sound["critical"] is False
    assert "not a fault" in sound["detail"] or "termux-media-player" in sound["detail"]


def test_sound_is_still_reported_honestly_off_android() -> None:
    """Reverse check: a Linux box with no audio should still say so."""
    import shutil as _shutil
    with patch("arena.system.doctor.sys.platform", "linux"), \
         patch("arena.hostplatform.is_android", return_value=False), \
         patch.object(_shutil, "which", return_value=None):
        checks = _doctor()
    assert checks["Sound"]["ok"] is False


def test_windows_keeps_its_own_sound_branch() -> None:
    """And the Windows path must not be collateral damage."""
    with patch("arena.system.doctor.sys.platform", "win32"):
        checks = _doctor()
    assert "Sound" in checks


def test_android_beep_uses_the_only_player_that_exists_there() -> None:
    import shutil as _shutil

    from arena.system import sound as snd

    calls: list[list[str]] = []

    def fake_which(name):
        return "/data/data/com.termux/files/usr/bin/termux-media-player" \
            if name == "termux-media-player" else None

    def fake_run(argv, **_kw):
        calls.append(list(argv))

        class R:
            returncode = 0
        return R()

    with patch.object(_shutil, "which", fake_which), \
         patch.object(snd.subprocess, "run", fake_run):
        result = snd.linux_play_beep("success", 800, 200)
    assert result["method"] == "termux-media-player"
    assert calls and calls[0][:2] == ["termux-media-player", "play"]


def test_access_handler_passes_the_provider_callables() -> None:
    """v4.169.17: without them every provider is 'callable not wired'.

    The first version called tunnels_status() bare, so /v1/access
    reported no tunnels on a bridge whose Tailscale funnel was serving
    the request being answered. /v1/tunnels/status, three hundred lines
    away in the same file, had always passed them.
    """
    src = (REPO_ROOT / "arena" / "admin" / "handlers_access.py").read_text(encoding="utf-8")
    for name in ("sys_funnel_status_sync", "cloudflared_status_sync",
                 "zerotier_status_sync", "ngrok_status_sync", "bore_status_sync"):
        assert name in src, f"{name} is not forwarded; that provider stays unwired"
    assert "run_in_executor" in src, "the provider probes shell out; do not block the loop"
