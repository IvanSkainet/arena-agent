"""The GPU row in `agentctl status` never printed, on any machine.

Bug #67. `arena/agentctl_extras/status.py` came back from the mutation
sweep with **224 of 224 mutants surviving** -- nothing executed the file
at all. That is not a weak-test signal, it is the absence of one, so the
file was read against the actual output of its data source.

`scripts/hwinfo.py` returns `gpu` as a **dict**::

    {"name": "NVIDIA RTX A2000", "vram_mb": 6144}

while the consumer treated it as a list of dicts::

    g = h_data.get('gpu', [])
    if g and len(g) >= 3:
        gpu_name = next((item["name"] for item in g if "name" in item), "?")

`len()` of that dict is 2 -- the number of KEYS -- so the guard was never
satisfied and the GPU line was silently skipped everywhere. Both halves
verified by execution: the condition is False for the real payload, and
forcing a third key makes the body raise `TypeError: string indices must
be integers`, because iterating a dict yields key strings.

A status command that omits a row is worse than one that raises. The
reader does not think "the tool is broken", they think "this machine has
no GPU".

The same pass fixed two neighbours found while proving the above:

* `int(platform.version().split('.')[-1])` for the Windows build number.
  The field is free-form, and a non-numeric tail raised straight through
  a command whose entire job is to report rather than fail. Non-Windows
  hosts were safe only by accident, through the `and` short circuit.
* Direct `h_data['os']['build']` indexing. `build` is null on Linux
  today, and a single `KeyError` was swallowed by the broad `except`
  around the block -- replacing the whole hardware section with one error
  line. A missing field should cost that field, not the report.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from arena.agentctl_extras.status import _gpu_entries, _os_label

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------
# The bug: consumer and producer disagreed about the shape.
# --------------------------------------------------------------------

def test_the_real_hwinfo_gpu_shape_yields_a_row():
    """This is the exact payload `hwinfo.py` produces. It must print."""
    payload = {"name": "NVIDIA RTX A2000", "vram_mb": 6144}
    assert list(_gpu_entries(payload)) == [("NVIDIA RTX A2000", 6144)]


def test_hwinfo_still_reports_gpu_as_a_mapping():
    """Pin the producer's shape so the two cannot drift apart again.

    If `hwinfo.py` ever switches to a list, `_gpu_entries` already
    handles it -- but this test failing is the signal to re-read the
    consumer rather than assume.
    """
    proc = subprocess.run(  # nosec B603 -- fixed argv, no shell
        [sys.executable, str(REPO / "scripts" / "hwinfo.py")],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        pytest.skip("hwinfo.py could not run in this environment")
    data = json.loads(proc.stdout)
    gpu = data.get("gpu")
    assert isinstance(gpu, (dict, list)), type(gpu)
    # Whatever it is, the consumer must not crash on it.
    list(_gpu_entries(gpu))


def test_a_list_of_adapters_also_works():
    """Multi-GPU hosts, or a future hwinfo revision."""
    payload = [
        {"name": "NVIDIA A100", "vram_mb": 40960},
        {"name": "Intel UHD", "vram_mb": 128},
    ]
    assert list(_gpu_entries(payload)) == [
        ("NVIDIA A100", 40960),
        ("Intel UHD", 128),
    ]


def test_a_two_key_mapping_is_not_rejected_for_being_short():
    """The regression itself: `len(g) >= 3` on a 2-key dict.

    Any guard that counts keys to decide whether a mapping is usable
    would fail this again.
    """
    assert list(_gpu_entries({"name": "GPU", "vram_mb": 1})) != []


@pytest.mark.parametrize("payload", [
    None, "", "RTX", 42, [], {}, ["a", "b"], [None], {"vram_mb": 6144},
    {"name": None, "vram_mb": None}, {"name": "", "vram_mb": 1},
])
def test_unusable_payloads_yield_nothing_instead_of_raising(payload):
    """Reverse of the failure mode: never crash the status command.

    And never print `GPU: ? (? MB VRAM)` -- a row with no information is
    noise that makes a real absence indistinguishable from a probe error.
    """
    assert list(_gpu_entries(payload)) == []


def test_a_missing_vram_still_names_the_card():
    """Knowing the model is worth a row even without the memory size."""
    assert list(_gpu_entries({"name": "RTX 4090"})) == [("RTX 4090", "?")]


# --------------------------------------------------------------------
# Neighbour 1: the Windows build number.
# --------------------------------------------------------------------

@pytest.mark.parametrize(("version", "expected"), [
    ("10.0.22631", "Windows 11"),
    ("10.0.26100", "Windows 11"),
    ("10.0.22000", "Windows 11"),   # exact boundary
    ("10.0.21999", "Windows 10"),
    ("10.0.19045", "Windows 10"),
])
def test_windows_build_classification(version, expected, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform, "version", lambda: version)
    assert _os_label() == expected


@pytest.mark.parametrize("version", ["6.3.9600.rc1", "", "10.0.preview", "x"])
def test_a_non_numeric_build_does_not_crash_the_status_command(
    version, monkeypatch
):
    """`int()` used to raise here, from a command that only reports."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform, "version", lambda: version)
    label = _os_label()
    assert label == "Windows (unknown build)"
    assert "11" not in label, "an unknown build must not be guessed as 11"


@pytest.mark.parametrize("system", ["Linux", "Darwin", "FreeBSD"])
def test_non_windows_is_reported_verbatim(system, monkeypatch):
    """These were safe only by accident before, via the `and` short circuit."""
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(
        platform, "version", lambda: "#1 SMP PREEMPT_DYNAMIC Debian 6.1.0-13"
    )
    assert _os_label() == system


# --------------------------------------------------------------------
# Neighbour 2: one missing key must not eat the whole report.
# --------------------------------------------------------------------

def test_the_source_uses_tolerant_lookups_for_optional_fields():
    """`build` is null on Linux right now; `[...]` would raise.

    Asserting on the source text rather than the output because the
    surrounding function prints to stdout and shells out; the property
    that matters is that no required-key indexing came back.
    """
    text = (REPO / "arena" / "agentctl_extras" / "status.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("h_data['os']['", "details['free_gb']",
                      "details['filesystem']"):
        assert forbidden not in text, (
            f"{forbidden} is back: a single missing key is swallowed by the "
            f"broad except and replaces the entire hardware section"
        )


def test_status_runs_end_to_end_without_raising(capsys):
    """The whole point of the command is that it always reports something."""
    from arena.agentctl_extras.status import run_status

    run_status()
    out = capsys.readouterr().out
    assert "### platform info" in out
    assert "### hardware info" in out


def test_run_status_has_no_mutable_default_argument():
    """`def run_status(args=[])` shares one list across every call."""
    import inspect

    from arena.agentctl_extras.status import run_status

    default = inspect.signature(run_status).parameters["args"].default
    assert not isinstance(default, (list, dict, set)), (
        "a mutable default is shared between calls; use None"
    )


# --------------------------------------------------------------------
# Bug #68: the Windows service state was read out of localized text.
# --------------------------------------------------------------------

def test_windows_service_state_does_not_depend_on_the_ui_language():
    """`"Running" in stdout` only works on an English install.

    Windows translates the Status column of `schtasks /fo TABLE`, so a
    genuinely running bridge reported "stopped" on German, French and
    Chinese hosts. Someone had already noticed on Russian and bolted
    "Выполняется" on beside it -- and then wrote "Running" a third time by
    mistake, which is the surviving mutant that led here.

    The fix drops text scraping entirely: the listening socket answers the
    question the operator is actually asking, while the scheduler entry
    only says whether Windows *would* start it.
    """
    text = (REPO / "arena" / "agentctl_extras" / "status.py").read_text(
        encoding="utf-8"
    )
    service_block = text[text.index("schtasks"):]
    for localized in ('"Running" in', "Выполняется", '"Ready" in',
                      "Wird ausgeführt", "正在运行"):
        assert localized not in service_block, (
            f"service state is being decided by the localized string "
            f"{localized!r}; that is wrong on every non-matching locale"
        )


def test_the_service_state_distinguishes_all_four_situations():
    """"stopped" alone hides whether the task is even registered."""
    text = (REPO / "arena" / "agentctl_extras" / "status.py").read_text(
        encoding="utf-8"
    )
    for phrase in ("no scheduled task", "scheduled task registered",
                   "could not query the task scheduler"):
        assert phrase in text, f"missing the {phrase!r} case"


def test_a_listening_port_outranks_the_scheduler_entry():
    """A bridge started by hand is running, task or no task.

    Mirrors the source ordering; if the branches are ever reordered so the
    scheduler wins, a manually started bridge would be reported stopped
    while it is serving requests.
    """
    text = (REPO / "arena" / "agentctl_extras" / "status.py").read_text(
        encoding="utf-8"
    )
    block = text[text.index("registered = r.returncode == 0"):]
    listening_at = block.index("if listening:")
    registered_at = block.index("elif registered")
    assert listening_at < registered_at
