"""Host classification, and the two bugs it exists to prevent.

`platform.system()` returns "Linux" on an Android phone. Everything the
bridge assumed about Linux -- systemd, a writable `~/.config`, a desktop
session -- is false there, and twenty-one call sites shell out to
`systemctl`.

The detector cannot be tested by running on a phone: CI has none, and
the sandbox has none. So every case here describes a device through its
environment, using values measured on a real one (POCO F7 Pro, Android
16, SDK 36, arm64-v8a, HyperOS 3, Termux installed):

    ANDROID_ROOT=/system
    ANDROID_DATA=/data
    PREFIX=/data/data/com.termux/files/usr    (inside Termux only)

This is the lesson from bug #75 applied before the fact rather than
after: when a fix depends on another platform's behaviour, simulate that
platform locally instead of letting CI be the only detector.

v4.167.2: every case pins `system=` explicitly. The first version let
the detector read the real OS, so the Android cases asserted
`'macos' == 'android'` on ten Windows and macOS jobs -- the test could
describe a phone's environment but not its operating system. Simulating
a platform means simulating all of it.
"""
from __future__ import annotations

import pytest

from arena import hostplatform as hp

# Environment of an `adb shell` session on the real device.
ANDROID_ADB_ENV = {
    "ANDROID_ROOT": "/system",
    "ANDROID_DATA": "/data",
    "HOME": "/",
    "PATH": "/product/bin:/apex/com.android.runtime/bin:/system/bin",
}

# Environment inside Termux on the same device.
TERMUX_ENV = {
    "ANDROID_ROOT": "/system",
    "ANDROID_DATA": "/data",
    "PREFIX": "/data/data/com.termux/files/usr",
    "HOME": "/data/data/com.termux/files/home",
    "TERMUX_VERSION": "0.118.0",
}

# An ordinary desktop. Must never be mistaken for a phone.
LINUX_DESKTOP_ENV = {
    "HOME": "/home/ivan",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "XDG_SESSION_TYPE": "wayland",
}


def test_an_android_phone_is_not_reported_as_plain_linux():
    """The whole point: "linux" is a true and useless answer on a phone."""
    assert hp.detect_host_class(ANDROID_ADB_ENV, system="Linux") == hp.ANDROID
    assert hp.is_android(ANDROID_ADB_ENV, system="Linux")


def test_termux_is_recognised_as_running_on_the_device():
    """Driving a phone and *being* one are different products.

    On-device there is no adb and none is needed; the bridge is the
    phone. That distinction drives the `backend` field in
    `/v1/capabilities`, so it has to be reliable.
    """
    assert hp.detect_host_class(TERMUX_ENV, system="Linux") == hp.ANDROID
    assert hp.is_termux(TERMUX_ENV, system="Linux") is True
    assert hp.termux_prefix(TERMUX_ENV) == "/data/data/com.termux/files/usr"

    described = hp.describe(TERMUX_ENV, system="Linux")
    assert described["role"] == "on-device"
    assert described["class"] == hp.ANDROID


def test_adb_shell_is_android_but_not_termux():
    """`adb shell` has Android's env but none of Termux's userland."""
    assert hp.is_android(ANDROID_ADB_ENV, system="Linux")
    assert hp.is_termux(ANDROID_ADB_ENV, system="Linux") is False
    assert hp.termux_prefix(ANDROID_ADB_ENV) is None
    assert hp.describe(ANDROID_ADB_ENV, system="Linux")["role"] == "android-host"


def test_a_linux_desktop_is_never_mistaken_for_a_phone(monkeypatch):
    """Reverse sabotage: a false Android verdict breaks a real desktop.

    If this ever returns ANDROID, every Linux user loses systemd
    handling, service management and autostart -- a far worse outcome
    than the bug being fixed. The filesystem probe is stubbed out
    because CI runners are Linux and must answer Linux.
    """
    monkeypatch.setattr(hp, "_paths_say_android", lambda: False)
    assert hp.detect_host_class(LINUX_DESKTOP_ENV, system="Linux") == hp.LINUX
    assert hp.is_android(LINUX_DESKTOP_ENV, system="Linux") is False
    assert hp.is_termux(LINUX_DESKTOP_ENV, system="Linux") is False


def test_a_stray_android_data_variable_does_not_make_a_desktop_a_phone(monkeypatch):
    """ANDROID_DATA alone appears in SDK tooling on developer machines.

    Requiring ANDROID_ROOT specifically is what keeps `adb`-adjacent
    desktops from being reclassified.
    """
    monkeypatch.setattr(hp, "_paths_say_android", lambda: False)
    env = dict(LINUX_DESKTOP_ENV, ANDROID_DATA="/data")
    assert hp.detect_host_class(env, system="Linux") == hp.LINUX


def test_a_stray_prefix_variable_alone_does_not_make_a_desktop_a_phone(monkeypatch):
    """PREFIX is easy to set by accident; it must corroborate, not decide."""
    monkeypatch.setattr(hp, "_paths_say_android", lambda: False)
    env = dict(LINUX_DESKTOP_ENV, PREFIX="/data/data/com.termux/files/usr")
    assert hp.detect_host_class(env, system="Linux") == hp.LINUX


@pytest.mark.parametrize("env", [ANDROID_ADB_ENV, TERMUX_ENV])
def test_android_never_claims_systemd(env):
    """Bug #76: `systemctl` on Android raises FileNotFoundError.

    `arena/agent_helpers/cli.py::doctor` called it unconditionally, so
    running the doctor on a phone killed it with a traceback instead of
    reporting the checks it had already passed.
    """
    assert hp.has_systemd(env, system="Linux") is False
    assert hp.describe(env, system="Linux")["systemd"] is False


@pytest.mark.parametrize("system,expected", [
    ("Windows", hp.WINDOWS),
    ("Darwin", hp.MACOS),
])
def test_desktop_operating_systems_are_never_android(system, expected):
    """Windows and macOS must short-circuit before any Android probing.

    A Windows host with ANDROID_ROOT set (an SDK install) would
    otherwise be misclassified, and every service call would break.
    """
    assert hp.detect_host_class(dict(ANDROID_ADB_ENV), system=system) == expected
    assert hp.is_android(dict(ANDROID_ADB_ENV), system=system) is False


def test_the_real_host_is_classified_without_arguments():
    """The zero-argument path is what production actually calls.

    Pinning `system=` everywhere else would let a broken default sail
    through, so this asserts the real machine gets a sane answer.
    """
    real = hp.detect_host_class()
    assert real in {hp.WINDOWS, hp.MACOS, hp.ANDROID, hp.LINUX, hp.UNKNOWN}
    assert hp.describe()["class"] == real


def test_detection_never_raises_on_a_hostile_environment():
    """A detector that throws is worse than one that guesses "linux".

    This runs on every capability request and on startup paths.
    """
    for env in ({}, {"ANDROID_ROOT": ""}, {"PREFIX": ""}, {"ANDROID_ROOT": "/"}):
        for system in (None, "Linux", "Windows", "Darwin", ""):
            assert isinstance(hp.detect_host_class(env, system=system), str)
            assert isinstance(hp.describe(env, system=system), dict)


def test_describe_is_json_safe():
    """It ships inside `/v1/capabilities`, so it must serialise."""
    import json

    for env in (ANDROID_ADB_ENV, TERMUX_ENV, LINUX_DESKTOP_ENV):
        json.dumps(hp.describe(env, system="Linux"))
