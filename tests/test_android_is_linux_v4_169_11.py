"""v4.169.11 -- Android is Linux for /proc, and is not Linux for systemd.

Two separate defects, both from collapsing those into one question:

1. Fourteen probes gated on ``platform.system() == "Linux"``. Python 3.13
   on Termux honestly answers ``"Android"``, so probes that only read
   ``/proc`` switched themselves off and returned
   ``"kernel modules probe is Linux-only"`` on a phone whose
   ``/proc/modules`` was readable. Verified on the device:
   ``/proc/modules``, ``/proc/meminfo`` and ``/proc/stat`` all exist.

2. Tailscale detection shells out to the ``tailscale`` binary. On Android
   Tailscale is an app (``com.tailscale.ipn``) behind VpnService with no
   CLI at all, so the phone reported the transport as missing. Confirmed
   on the device: the package is installed and
   ``ip addr show tailscale0`` says the interface does not exist.

These run on Linux CI and fake the platform, because the rule in
AGENTS.md is that a fix resting on OS behaviour needs a test that
impersonates the other platform -- otherwise it is only ever proven on
the machine that did not have the bug.
"""
from __future__ import annotations

from arena import hostplatform
from arena.mobile import tailscale_android

ANDROID_ENV = {
    "PREFIX": "/data/data/com.termux/files/usr",
    "TERMUX_VERSION": "0.118.0",
    "HOME": "/data/data/com.termux/files/home",
}


def test_android_counts_as_a_linux_kernel() -> None:
    assert hostplatform.has_linux_kernel(ANDROID_ENV, "Android") is True
    assert hostplatform.has_linux_kernel({}, "Linux") is True
    assert hostplatform.has_linux_kernel({}, "Windows") is False
    assert hostplatform.has_linux_kernel({}, "Darwin") is False


def test_android_does_not_count_as_systemd() -> None:
    """The distinction the old code missed, in one assertion pair."""
    assert hostplatform.has_systemd(ANDROID_ENV, "Android") is False
    assert hostplatform.has_linux_kernel(ANDROID_ENV, "Android") is True


def test_probe_gates_use_the_kernel_question_not_the_distro_one() -> None:
    """Reading /proc must not be refused just because the OS says Android."""
    import ast

    from arena.inventory import probe_agent_facts, probe_agent_sys

    for module, names in (
        (probe_agent_facts, ("get_kernel_modules", "get_cpu_vulnerabilities")),
        (probe_agent_sys, ("get_dmesg_errors",)),
    ):
        text = open(module.__file__ or "", encoding="utf-8").read()
        tree = ast.parse(text)
        found = {f.name: f for f in tree.body if isinstance(f, ast.FunctionDef)}
        for name in names:
            assert name in found, f"{name} vanished from {module.__name__}"
            # Slice by AST, not str.index -- a textual slice runs past the
            # end of the function and swallows its neighbours.
            body = ast.unparse(found[name])
            assert 'platform.system() != \'Linux\'' not in body, (
                f"{name} still gates on the distro question; on Android that "
                f"switches off a probe whose /proc files are readable"
            )


def test_systemd_probes_say_what_is_actually_missing() -> None:
    from arena.inventory import probe_agent_facts, probe_agent_sys

    for module, name in ((probe_agent_facts, "get_systemd_failed"),
                         (probe_agent_sys, "get_journal_errors")):
        source = open(module.__file__ or "", encoding="utf-8").read()
        body = source[source.index(f"def {name}("):]
        assert "has_systemd()" in body[:600], f"{name} must ask has_systemd()"


# --- Tailscale on Android --------------------------------------------------

def test_tailscale_android_reports_absent_package_honestly(monkeypatch) -> None:
    monkeypatch.setattr(tailscale_android, "package_installed", lambda: False)
    monkeypatch.setattr(tailscale_android, "cgnat_addresses", lambda: [])
    info = tailscale_android.status()
    assert info["installed"] is False
    assert info["connected"] is False
    assert "no CLI" in info["reason"]


def test_tailscale_android_does_not_guess_connected_from_a_package_listing(monkeypatch) -> None:
    """Installed is a fact; connected is a different claim.

    The desktop adapter infers `installed` from "any status string came
    back". Carrying that habit over would make a phone with the app but
    the VPN switched off report a working transport.
    """
    monkeypatch.setattr(tailscale_android, "package_installed", lambda: True)
    monkeypatch.setattr(tailscale_android, "cgnat_addresses", lambda: [])
    info = tailscale_android.status()
    assert info["installed"] is True
    assert info["connected"] is False
    assert "switched off" in info["reason"]


def test_tailscale_android_claims_connected_only_on_a_tailnet_address(monkeypatch) -> None:
    monkeypatch.setattr(tailscale_android, "package_installed", lambda: True)
    monkeypatch.setattr(tailscale_android, "cgnat_addresses", lambda: ["100.101.102.103"])
    info = tailscale_android.status()
    assert info["connected"] is True
    assert info["addresses"] == ["100.101.102.103"]


def test_cgnat_range_is_not_confused_with_ordinary_lan_addresses(monkeypatch) -> None:
    """100.x outside the CGNAT block, and normal LAN IPs, must not count."""
    sample = (
        "1: lo    inet 127.0.0.1/8 scope host lo\n"
        "2: wlan0 inet 192.168.50.181/24 brd 192.168.50.255 scope global wlan0\n"
        "3: rmnet inet 100.200.1.5/16 scope global rmnet\n"
    )
    monkeypatch.setattr(tailscale_android.shutil, "which", lambda _n: "/system/bin/ip")
    monkeypatch.setattr(tailscale_android, "_run", lambda *_a, **_k: sample)
    assert tailscale_android.cgnat_addresses() == []

    sample_with_tailnet = sample + "4: tun0 inet 100.90.1.2/32 scope global tun0\n"
    monkeypatch.setattr(tailscale_android, "_run", lambda *_a, **_k: sample_with_tailnet)
    assert tailscale_android.cgnat_addresses() == ["100.90.1.2"]


def test_tunnels_routes_android_to_the_app_adapter(monkeypatch) -> None:
    """The desktop CLI path must not be reached on a phone."""
    from arena.admin import tunnels

    monkeypatch.setattr(tunnels, "is_android", lambda: True)

    def explode() -> dict:  # pragma: no cover -- must never run
        raise AssertionError("desktop tailscale CLI path used on Android")

    info = tunnels._tailscale_snapshot(explode)
    assert info["platform"] == "android"
    assert info["cli"] is False


def test_tunnels_still_uses_the_cli_adapter_off_android(monkeypatch) -> None:
    """Reverse check: desktops must keep the binary-based path."""
    from arena.admin import tunnels

    monkeypatch.setattr(tunnels, "is_android", lambda: False)
    info = tunnels._tailscale_snapshot(lambda: {"tailscale": {"connected": True},
                                                "funnel": {"active": True}})
    assert info.get("platform") != "android"
    assert info["connected"] is True
