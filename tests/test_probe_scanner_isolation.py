"""T74: barrier-controlled proof that shared probe inputs cause scanner races."""
import shutil
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import Event

import pytest

from scripts import test_import_failopen_guard as guard

_EVENTS = ("probe_ready", "enumerated", "deleted")


class _RaceLog:
    """What the race had reached, so a timeout tells slow from blocked (#517)."""

    def __init__(self):
        """Start the clock every later entry is measured from."""
        self.started = time.monotonic()
        self.reached = {}
        self.scans = []

    def reach(self, name, event):
        """Record when a step was reached, then set its event."""
        self.reached[name] = time.monotonic() - self.started
        event.set()

    def scan(self, path):
        """Record that the scan of one file began."""
        self.scans.append((path.name, time.monotonic() - self.started))

    def report(self, now=None):
        """Describe the steps reached and the last file whose scan began."""
        elapsed = (time.monotonic() - self.started) if now is None else now
        lines = [f"after {elapsed:.1f}s"]
        for name in _EVENTS:
            at = self.reached.get(name)
            lines.append(f"{name}: " + ("not reached" if at is None else f"reached at {at:.1f}s"))
        if not self.scans:
            return "\n".join([*lines, "files whose scan began: 0"])
        name, at = self.scans[-1]
        lines.append(
            f"files whose scan began: {len(self.scans)}; "
            f"last: {name}, began at {at:.1f}s ({elapsed - at:.1f}s before this report)"
        )
        return "\n".join(lines)


def _result_or_report(future, timeout, log):
    """Return the future's result; on a timeout fail with what the race had reached."""
    try:
        return future.result(timeout=timeout)
    except FutureTimeout:
        raise AssertionError(f"no result within {timeout}s\n{log.report()}") from None


@pytest.mark.parametrize("shared_inputs", [False, True])
def test_probe_deletion_race_requires_shared_scanner_inputs(
    isolated_ratchet_repo, tmp_path, monkeypatch, shared_inputs,
):
    # Both positive and deliberately broken controls use temporary copies.
    # Never reproduce the old defect by mutating the developer's checkout.
    scanner_root = tmp_path / "scanner"
    shutil.copytree(isolated_ratchet_repo / "tests", scanner_root / "tests")
    writer_root = scanner_root if shared_inputs else isolated_ratchet_repo
    probe = writer_root / "tests" / "test_zz_t74_race_probe.py"
    probe_ready = Event()
    enumerated = Event()
    deleted = Event()
    original_scan = guard.scan_file
    # Upper bounds, not delays: every wait ends the moment its event is set.
    # They were 10 and 20 seconds, and a hosted Windows runner under two
    # workers needed longer than that to scan the copied test tree.
    step, whole = 60, 120
    log = _RaceLog()

    def scan(path):
        log.scan(path)
        # collect() has completed its candidate snapshot before it scans
        # conftest.py, which sorts before our injected test_zz_* candidate.
        if path == scanner_root / "tests" / "conftest.py":
            log.reach("enumerated", enumerated)
            assert deleted.wait(step), "writer did not finish deletion\n" + log.report()
        return original_scan(path)

    def writer():
        try:
            probe.write_text("def test_probe():\n    assert True\n", encoding="utf-8")
            log.reach("probe_ready", probe_ready)
            assert enumerated.wait(step), "scanner did not enumerate inputs\n" + log.report()
        finally:
            probe.unlink(missing_ok=True)
            log.reach("deleted", deleted)

    def reader():
        assert probe_ready.wait(step), "writer did not create its probe\n" + log.report()
        return guard.collect()

    monkeypatch.setattr(guard, "root_path", lambda: scanner_root)
    monkeypatch.setattr(guard, "tests_path", lambda: scanner_root / "tests")
    monkeypatch.setattr(guard, "scan_file", scan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(writer)
        reading = pool.submit(reader)
        if shared_inputs:
            with pytest.raises(FileNotFoundError, match="test_zz_t74_race_probe"):
                _result_or_report(reading, whole, log)
        else:
            assert _result_or_report(reading, whole, log) == []
        _result_or_report(writing, whole, log)


def test_a_race_that_times_out_says_which_step_it_had_reached():
    log = _RaceLog()
    log.reached = {"probe_ready": 0.2, "enumerated": 1.5}
    log.scans = [("conftest.py", 1.5), ("test_a.py", 2.0)]

    assert log.report(now=62.0).splitlines() == [
        "after 62.0s",
        "probe_ready: reached at 0.2s",
        "enumerated: reached at 1.5s",
        "deleted: not reached",
        "files whose scan began: 2; last: test_a.py, began at 2.0s (60.0s before this report)",
    ]


def test_the_log_records_each_step_and_each_file_as_it_happens(tmp_path):
    log = _RaceLog()
    event = Event()

    log.reach("enumerated", event)
    log.scan(tmp_path / "conftest.py")
    log.scan(tmp_path / "test_a.py")

    assert event.is_set()
    assert list(log.reached) == ["enumerated"]
    assert [name for name, _at in log.scans] == ["conftest.py", "test_a.py"]
    assert 0 <= log.reached["enumerated"] <= log.scans[0][1] <= log.scans[1][1]


def test_a_race_that_scanned_nothing_says_so():
    assert _RaceLog().report(now=120.0).splitlines() == [
        "after 120.0s",
        "probe_ready: not reached",
        "enumerated: not reached",
        "deleted: not reached",
        "files whose scan began: 0",
    ]


def test_a_result_that_never_arrives_fails_with_the_report_instead_of_a_bare_timeout():
    log = _RaceLog()
    log.reach("probe_ready", Event())

    pending = Future()

    with pytest.raises(AssertionError) as raised:
        _result_or_report(pending, 0.01, log)

    message = str(raised.value)
    assert message.startswith("no result within 0.01s\nafter ")
    assert "probe_ready: reached at " in message
    assert "enumerated: not reached" in message


def test_a_result_that_arrives_is_returned_and_its_own_error_is_kept():
    done = Future()
    done.set_result(["finding"])
    assert _result_or_report(done, 0.01, _RaceLog()) == ["finding"]

    failed = Future()
    failed.set_exception(FileNotFoundError("test_zz_t74_race_probe"))
    log = _RaceLog()
    with pytest.raises(FileNotFoundError, match="test_zz_t74_race_probe"):
        _result_or_report(failed, 0.01, log)
