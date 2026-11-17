"""Runner-owned event input boundary: reject paths before opening them."""
from __future__ import annotations

import pathlib

import pytest

from arena import security_alerts as gate


@pytest.fixture
def runner_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    directory = tmp_path / "_github_workflow"
    directory.mkdir()
    event = directory / "event.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    return event


@pytest.mark.parametrize("location", ["outside", "traversal", "relative", "wrong_name", "missing_root"])
def test_event_reader_rejects_untrusted_locations_before_open(
    runner_environment, monkeypatch, location
):
    event = runner_environment
    tmp_path = event.parent.parent
    event.write_text('{"number": 77}', encoding="utf-8")
    locations = {
        "outside": tmp_path / "event.json",
        "traversal": event.parent / ".." / "_github_workflow" / "event.json",
        "relative": pathlib.Path("_github_workflow/event.json"),
        "wrong_name": event.with_name("credentials.json"),
        "missing_root": event,
    }
    (tmp_path / "event.json").write_text('{"number": 999}', encoding="utf-8")
    event.with_name("credentials.json").write_text('{"number": 999}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    if location == "missing_root":
        monkeypatch.delenv("RUNNER_TEMP")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(locations[location]))

    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("untrusted event path reached open")

    monkeypatch.setattr(pathlib.Path, "open", forbidden_open)
    assert gate._event_payload() is None


def test_event_reader_rejects_symlink_to_outside_file(runner_environment):
    tmp_path = runner_environment.parent.parent
    outside = tmp_path / "outside.json"
    outside.write_text('{"number": 999}', encoding="utf-8")
    event = runner_environment
    try:
        event.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires filesystem/OS support")
    assert gate._event_payload() is None


def test_event_reader_rejects_oversized_payload(runner_environment):
    event = runner_environment
    event.write_text('{"value":"' + 'x' * (8 * 1024 * 1024) + '"}', encoding="utf-8")
    assert gate._event_payload() is None


def test_event_reader_rejects_non_regular_file(runner_environment):
    event = runner_environment
    event.mkdir()
    assert gate._event_payload() is None


def test_event_reader_rejects_symlinked_workflow_directory(runner_environment):
    tmp_path = runner_environment.parent.parent
    directory = tmp_path / "_github_workflow"
    directory.rmdir()
    outside = tmp_path / "other-workflow"
    outside.mkdir()
    (outside / "event.json").write_text('{"number": 999}', encoding="utf-8")
    try:
        directory.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks require filesystem/OS support")
    assert gate._event_payload() is None
