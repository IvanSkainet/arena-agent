"""What supervises the bridge on a phone must be reported honestly.

Android sets `sys.platform == "linux"`, so `_service_info_sync` fell
into the Linux branch and shelled out to `systemctl` -- which does not
exist in Termux. The result was `running_as: "unknown"` on every phone,
measured on a POCO F7 Pro running v4.168.0, and the Dashboard showed
"Manual / unmanaged" even when the boot hook was in place.

"unknown" is not a lie exactly, but it is useless, and it hides the one
distinction the operator actually needs: the bootstrap writes a
`~/.termux/boot` hook, but nothing runs that hook unless the Termux:Boot
app is installed from F-Droid. A bridge with a hook and no app looks
identical to a bridge with working autostart, right up until the phone
reboots and the bridge does not come back.

So there are three states, and they must stay distinguishable.
"""
from __future__ import annotations

from unittest import mock

import pytest

import arena.service.info as info


@pytest.fixture
def on_android():
    with mock.patch.object(info, "_is_android", return_value=True):
        yield


def _fake_pm(found: bool):
    """Stand in for `pm path com.termux.boot`."""
    result = mock.Mock()
    result.returncode = 0 if found else 1
    result.stdout = "package:/data/app/com.termux.boot/base.apk" if found else ""
    return result


def test_hook_plus_app_is_real_autostart(on_android):
    with mock.patch("pathlib.Path.is_file", return_value=True), \
         mock.patch("pathlib.Path.exists", return_value=True):
        result = info._service_info_sync()
    assert result["running_as"] == "termux-boot"
    assert result["termux_boot"]["hook_present"] is True
    assert result["termux_boot"]["app_installed"] is True


def test_a_hook_with_no_app_is_not_reported_as_autostart(on_android):
    """The state the bootstrap actually leaves behind.

    Reporting this as working autostart would be the bug #66 shape --
    the bridge claiming a durability it does not have. The operator
    finds out at the next reboot, which is the worst possible time.
    """
    with mock.patch("pathlib.Path.is_file", return_value=True), \
         mock.patch("pathlib.Path.exists", return_value=False), \
         mock.patch("subprocess.run", return_value=_fake_pm(False)):
        result = info._service_info_sync()

    assert result["running_as"] == "termux-boot-hook-only"
    assert result["running_as"] != "termux-boot", "hook-only claimed as autostart"
    note = result["termux_boot"]["note"].lower()
    assert "f-droid" in note, "the note does not say how to fix it"


def test_no_hook_is_manual(on_android):
    with mock.patch("pathlib.Path.is_file", return_value=False), \
         mock.patch("pathlib.Path.exists", return_value=False), \
         mock.patch("subprocess.run", return_value=_fake_pm(False)):
        result = info._service_info_sync()
    assert result["running_as"] == "manual"


def test_the_package_manager_is_consulted_when_the_data_dir_is_unreadable(on_android):
    """`/data/data/com.termux.boot` is not world-readable on every device.

    Relying on the directory alone would report "hook only" on a phone
    where the app is installed and working -- a false negative that
    tells the operator to install something they already have.
    """
    with mock.patch("pathlib.Path.is_file", return_value=True), \
         mock.patch("pathlib.Path.exists", return_value=False), \
         mock.patch("subprocess.run", return_value=_fake_pm(True)):
        result = info._service_info_sync()
    assert result["running_as"] == "termux-boot"


def test_android_never_shells_out_to_systemctl(on_android):
    """The original defect: `systemctl` does not exist in Termux.

    Asserting the call is absent rather than that the output looks
    right, because a missing binary fails quietly here -- the except
    swallowed it and left `unknown`.
    """
    with mock.patch("pathlib.Path.is_file", return_value=True), \
         mock.patch("pathlib.Path.exists", return_value=True), \
         mock.patch("subprocess.run") as spawned:
        info._service_info_sync()

    for call in spawned.call_args_list:
        argv = call.args[0] if call.args else []
        assert "systemctl" not in argv, (
            f"Android path invoked systemd: {argv}")
        assert "launchctl" not in argv, (
            f"Android path invoked launchd: {argv}")


def test_detection_failure_does_not_break_the_service_surface():
    """A detector that raises must not take `/v1/service/info` with it."""
    with mock.patch("arena.hostplatform.is_android",
                    side_effect=RuntimeError("boom")):
        assert info._is_android() is False


def test_desktop_platforms_are_untouched():
    """Reverse sabotage: Linux and Windows must keep their own branches.

    If `_is_android()` ever returned True on a desktop, the bridge would
    start looking for a Termux boot hook on a systemd machine and report
    `manual` to someone whose systemd unit is running fine.
    """
    with mock.patch.object(info, "_is_android", return_value=False), \
         mock.patch("sys.platform", "linux"), \
         mock.patch("subprocess.run") as spawned:
        spawned.return_value = mock.Mock(stdout="active\n", returncode=0)
        result = info._service_info_sync()

    assert result["running_as"] == "systemd-user"
    assert "termux_boot" not in result
