"""nvidia-smi output that made the GPU disappear entirely.

`_query_gpu_devices` had 0% coverage and came back from the mutation
sweep untouched, which is not a weak-test signal -- it is no signal.
Reading it against real nvidia-smi behaviour found two live defects, both
of which report "you have no GPU" for a machine that plainly has one:

* **"[N/A]"** -- nvidia-smi prints this for a field it cannot read, which
  is routine on vGPU and MIG partitions. `int(float("[N/A]"))` raised
  inside the try, and the bare `continue` threw away the WHOLE device.
  An A100 with an unreadable utilisation column reported backend "none"
  and an empty list.
* **a comma in the device name** -- the CSV is unquoted, so
  "NVIDIA RTX A2000, Laptop" split into seven fields, shifted every
  column by one, failed the int() and dropped the card.

A dashboard that says "no GPU" when a field is missing is worse than one
that says nothing: it answers a question it does not know the answer to.
"""
from __future__ import annotations

import types
from unittest.mock import patch

import pytest

# The parsing moved to gpu_probe.py in v4.165.0 when live_metrics.py
# crossed the 600-line runtime cap during this fix. Patch the module that
# actually owns `shutil`/`subprocess`, not the one that re-exports the
# functions -- patching the re-exporter would silently stop intercepting.
import arena.observability.gpu_probe as lm


def _with_smi(stdout: str, returncode: int = 0):
    def fake_which(name):
        return "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None

    def fake_run(*args, **kwargs):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return patch.object(lm.shutil, "which", fake_which), patch.object(
        lm.subprocess, "run", fake_run
    )


def _query(stdout: str, returncode: int = 0) -> dict:
    which_patch, run_patch = _with_smi(stdout, returncode)
    with which_patch, run_patch:
        return lm._query_gpu_devices()


def test_a_normal_single_card_parses():
    result = _query("0, NVIDIA RTX A2000, 8, 1024, 40960, 41")
    assert result["available"] is True
    assert result["backend"] == "nvidia-smi"
    (device,) = result["devices"]
    assert device["index"] == 0
    assert device["name"] == "NVIDIA RTX A2000"
    assert device["gpu_util_percent"] == 8
    assert device["mem_used_bytes"] == 1024 * 1024 * 1024
    assert device["temperature_c"] == 41


def test_an_unreadable_field_does_not_delete_the_card():
    """The A100/MIG case. Missing field -> null, not a missing GPU."""
    result = _query("0, NVIDIA A100-SXM4-40GB, [N/A], 1024, 40960, 35")
    assert result["backend"] == "nvidia-smi", "the card vanished"
    (device,) = result["devices"]
    assert device["name"] == "NVIDIA A100-SXM4-40GB"
    assert device["gpu_util_percent"] is None, (
        "an unreadable utilisation must be null, never 0 -- 0 reads as a "
        "confidently idle GPU"
    )
    # Everything that WAS readable still comes through.
    assert device["mem_used_bytes"] == 1024 * 1024 * 1024
    assert device["temperature_c"] == 35


@pytest.mark.parametrize("missing", ["[N/A]", "N/A", "", "   "])
def test_every_unreadable_spelling_becomes_null(missing):
    result = _query(f"0, GPU, {missing}, 1024, 40960, {missing}")
    (device,) = result["devices"]
    assert device["gpu_util_percent"] is None
    assert device["temperature_c"] is None


def test_a_comma_in_the_device_name_does_not_shift_the_columns():
    """nvidia-smi does not quote the name field."""
    result = _query("0, NVIDIA GeForce RTX 4090, Laptop GPU, 12, 2048, 16384, 55")
    assert result["backend"] == "nvidia-smi", "the card vanished"
    (device,) = result["devices"]
    assert device["name"] == "NVIDIA GeForce RTX 4090, Laptop GPU"
    assert device["gpu_util_percent"] == 12
    assert device["mem_used_bytes"] == 2048 * 1024 * 1024
    assert device["mem_total_bytes"] == 16384 * 1024 * 1024
    assert device["temperature_c"] == 55


def test_multiple_cards_are_independent():
    """One bad row must not take the healthy card down with it."""
    result = _query(
        "0, NVIDIA A, 8, 1024, 40960, 41\n"
        "1, NVIDIA B, [N/A], 2048, 40960, [N/A]"
    )
    first, second = result["devices"]
    assert first["gpu_util_percent"] == 8
    assert second["index"] == 1
    assert second["gpu_util_percent"] is None
    assert second["mem_used_bytes"] == 2048 * 1024 * 1024


def test_unparseable_output_reports_no_backend_rather_than_guessing():
    """Reverse sabotage: leniency must not become "invent a device"."""
    for junk in ("garbage line", "", "   \n  ", "only,three,fields"):
        result = _query(junk)
        assert result["devices"] == [], junk
        assert result["backend"] == "none", junk
        assert result["available"] is False, junk


def test_a_nonzero_exit_is_not_treated_as_data():
    result = _query("0, GPU, 8, 1024, 40960, 41", returncode=9)
    assert result["backend"] == "none"


def test_no_nvidia_smi_on_path_is_not_an_error():
    with patch.object(lm.shutil, "which", lambda name: None):
        result = lm._query_gpu_devices()
    assert result == {"available": False, "backend": "none", "devices": []}


@pytest.mark.parametrize(
    ("text", "expected"),
    [("8", 8), ("8.7", 8), ("[N/A]", None), ("N/A", None), ("", None), ("x", None)],
)
def test_smi_int_parsing(text, expected):
    assert lm._smi_int(text) == expected


def test_smi_bytes_conversion_is_mib_not_bytes():
    """nvidia-smi's --nounits memory columns are MiB.

    Reading them as bytes would under-report a 40 GB card as 40 KB, which
    is the kind of quietly-wrong number a sparkline never reveals.
    """
    assert lm._smi_bytes_from_mib("40960") == 40960 * 1024 * 1024
    assert lm._smi_bytes_from_mib("[N/A]") is None
