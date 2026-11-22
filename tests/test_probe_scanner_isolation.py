"""T74: barrier-controlled proof that shared probe inputs cause scanner races."""
import shutil
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from scripts import test_import_failopen_guard as guard


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

    def scan(path):
        # collect() has completed its candidate snapshot before it scans
        # conftest.py, which sorts before our injected test_zz_* candidate.
        if path == scanner_root / "tests" / "conftest.py":
            enumerated.set()
            assert deleted.wait(10), "writer did not finish deletion"
        return original_scan(path)

    def writer():
        try:
            probe.write_text("def test_probe():\n    assert True\n", encoding="utf-8")
            probe_ready.set()
            assert enumerated.wait(10), "scanner did not enumerate inputs"
        finally:
            probe.unlink(missing_ok=True)
            deleted.set()

    def reader():
        assert probe_ready.wait(10), "writer did not create its probe"
        return guard.collect()

    monkeypatch.setattr(guard, "root_path", lambda: scanner_root)
    monkeypatch.setattr(guard, "tests_path", lambda: scanner_root / "tests")
    monkeypatch.setattr(guard, "scan_file", scan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(writer)
        reading = pool.submit(reader)
        if shared_inputs:
            with pytest.raises(FileNotFoundError, match="test_zz_t74_race_probe"):
                reading.result(timeout=20)
        else:
            assert reading.result(timeout=20) == []
        writing.result(timeout=20)
