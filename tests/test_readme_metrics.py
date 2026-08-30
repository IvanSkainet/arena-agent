"""The README metrics block must stay generated, current, and self-checking.

Hand-typed statistics in a README rot silently. These tests pin the generator
and -- more importantly -- its failure branches, because a freshness gate that
cannot report staleness is decoration.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "render_readme_metrics.py"
README = REPO_ROOT / "README.md"


def _load():
    spec = importlib.util.spec_from_file_location("render_readme_metrics", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def renderer():
    return _load()


def test_script_exists():
    assert SCRIPT.is_file(), f"{SCRIPT} is missing; CI references it"


def test_readme_has_the_markers():
    text = README.read_text(encoding="utf-8")
    assert text.count(_load().BEGIN) == 1, "exactly one BEGIN marker expected"
    assert text.count(_load().END) == 1, "exactly one END marker expected"


def test_readme_block_is_current(renderer):
    """The committed block must match what the generator produces now."""
    assert renderer.main(["--check"]) == 0, (
        "README metrics are stale; run: python scripts/render_readme_metrics.py"
    )


def test_counts_are_plausible(renderer):
    """Guards against a glob change that silently counts almost nothing."""
    m = renderer.collect()
    assert m["runtime_lines"] > 10_000, f"runtime line count implausible: {m}"
    assert m["test_lines"] > 10_000, f"test line count implausible: {m}"
    assert m["runtime_files"] > 100 and m["test_files"] > 100, m
    assert m["workflows"] >= 1 and m["gates"] >= 1, m


def test_the_generated_block_excludes_itself(renderer):
    """The counter must not count its own output.

    It does now only because the metrics come from source globs; if someone
    later counts README.md too, writing the table would change the number the
    table reports and --check could never converge.
    """
    m1 = renderer.collect()
    renderer.main([])           # rewrite
    m2 = renderer.collect()
    assert m1 == m2, f"rendering changed the measured values: {m1} -> {m2}"
    assert renderer.main(["--check"]) == 0, "not idempotent: --check fails after a write"


def test_check_reports_a_missing_block(renderer, tmp_path, monkeypatch):
    """No markers must be a loud failure, not a silent pass."""
    fake = tmp_path / "README.md"
    fake.write_text("# no markers here\n", encoding="utf-8")
    monkeypatch.setattr(renderer, "README", fake)
    assert renderer.main(["--check"]) == 1


def test_check_reports_stale_numbers(renderer, tmp_path, monkeypatch, capsys):
    """A figure well outside tolerance must fail."""
    m = renderer.collect()
    m["runtime_lines"] = int(m["runtime_lines"] * 2) + 1000   # far outside tolerance
    fake = tmp_path / "README.md"
    fake.write_text(f"intro\n{renderer.render(m)}\noutro\n", encoding="utf-8")
    monkeypatch.setattr(renderer, "README", fake)
    assert renderer.main(["--check"]) == 1, "a doubled line count was accepted as current"
    assert "out of date" in capsys.readouterr().out


def test_small_drift_is_tolerated(renderer, tmp_path, monkeypatch):
    """A one-line change must not turn CI red until someone reruns a script."""
    m = renderer.collect()
    m["runtime_lines"] = int(m["runtime_lines"] * 1.01)  # 1% drift
    fake = tmp_path / "README.md"
    fake.write_text(f"intro\n{renderer.render(m)}\noutro\n", encoding="utf-8")
    monkeypatch.setattr(renderer, "README", fake)
    assert renderer.main(["--check"]) == 0, "1% drift should be tolerated"


def test_tolerance_cannot_be_widened_into_uselessness(renderer):
    """A tolerance big enough to accept anything is the same as no gate.

    Found by sabotage: raising TOLERANCE to 10.0 left every other test green
    while the freshness check accepted a 1000% error.
    """
    assert 0 < renderer.TOLERANCE <= 0.10, (
        f"TOLERANCE is {renderer.TOLERANCE}; above 10% the check stops "
        f"distinguishing a current README from an abandoned one"
    )


def test_check_actually_rejects_a_grossly_wrong_figure(renderer, tmp_path, monkeypatch):
    """Drive the whole --check path with a number far outside any tolerance.

    Found by sabotage: replacing `if stale:` with `if False:` disabled the
    staleness report and the suite stayed green, because the other tests only
    ever exercised the passing path.
    """
    m = renderer.collect()
    m["runtime_lines"] = 1          # unmistakably wrong
    m["test_lines"] = 1
    fake = tmp_path / "README.md"
    fake.write_text(f"intro\n{renderer.render(m)}\noutro\n", encoding="utf-8")
    monkeypatch.setattr(renderer, "README", fake)
    assert renderer.main(["--check"]) == 1, (
        "--check accepted a README claiming 1 line of code; the staleness "
        "branch is not doing anything"
    )


def test_the_ratio_is_covered_by_the_freshness_check(renderer, tmp_path, monkeypatch):
    """A wrong test-to-code ratio must fail --check.

    Found in review: the number pattern only matched bold integers, so the
    decimal ratio was never compared and could display any value.
    """
    block = renderer.render(renderer.collect())
    ratio_line = next(line for line in block.splitlines() if "ratio" in line)
    broken = block.replace(ratio_line, "| Test-to-code ratio | **9.99x** |")
    assert broken != block, "could not perturb the ratio line"
    fake = tmp_path / "README.md"
    fake.write_text(f"intro\n{broken}\noutro\n", encoding="utf-8")
    monkeypatch.setattr(renderer, "README", fake)
    assert renderer.main(["--check"]) == 1, (
        "--check accepted a fabricated test-to-code ratio"
    )


def test_production_files_are_not_dropped_for_having_test_in_the_name(renderer):
    """Runtime CDP handlers are named test_*.py but are production code.

    Found in review: filtering runtime files on `"test" in name` removed 1,114
    lines of shipped code from the count.
    """
    # as_posix(): on Windows str() yields backslashes and never matches.
    counted = {p.relative_to(renderer.REPO_ROOT).as_posix() for p in renderer.runtime_paths()}
    for shipped in ("arena/browser/cdp/test_launch.py", "scripts/check_latest_release.py"):
        if (renderer.REPO_ROOT / shipped).exists():
            assert shipped in counted, f"{shipped} is production code but was excluded"


def test_unreadable_input_fails_closed(renderer, tmp_path):
    """A file the script cannot read must abort, not shrink the totals."""
    missing = tmp_path / "gone.py"
    missing.write_text("x = 1\n", encoding="utf-8")
    missing.unlink()
    with pytest.raises(SystemExit):
        renderer._count([missing])


def test_exclusions_match_path_components_not_substrings(renderer, monkeypatch, tmp_path):
    """A checkout under a directory named .venv must still be counted.

    Substring matching on the absolute path would exclude every file in the
    project depending only on where CI happens to check it out.
    """
    root = tmp_path / ".venv-cache" / "arena-agent"
    (root / "arena").mkdir(parents=True)
    (root / "arena" / "mod.py").write_text("a = 1\n", encoding="utf-8")
    (root / "arena" / "__pycache__").mkdir()
    (root / "arena" / "__pycache__" / "junk.py").write_text("junk\n", encoding="utf-8")
    monkeypatch.setattr(renderer, "REPO_ROOT", root)
    found = {p.name for p in renderer._iter_files(("arena/**/*.py",))}
    assert "mod.py" in found, "a real file was excluded because a PARENT dir contained .venv"
    assert "junk.py" not in found, "__pycache__ must still be excluded"


def test_hand_editing_the_table_is_detected(renderer, tmp_path, monkeypatch):
    """Renaming a row must fail --check even though the figures still match.

    Found by sabotage: the check compared only numbers, so the labels around
    them could say anything.
    """
    block = renderer.render(renderer.collect()).replace("| Runtime code |", "| Runtime CODE |")
    fake = tmp_path / "README.md"
    fake.write_text(f"intro\n{block}\noutro\n", encoding="utf-8")
    monkeypatch.setattr(renderer, "README", fake)
    assert renderer.main(["--check"]) == 1, "a hand-edited table was accepted as current"
