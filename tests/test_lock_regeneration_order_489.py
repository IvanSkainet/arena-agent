"""T73: dependent locks must resolve against freshly generated constraints."""
from __future__ import annotations

from pathlib import Path
from unittest import TestCase

import pytest

from arena.lock_regeneration import regeneration_order

CHECK = TestCase()


def _input(root: Path, name: str, text: str = "") -> None:
    (root / name).write_text(text, encoding="utf-8")


def test_shared_pin_bump_reaches_every_consumer(tmp_path: Path) -> None:
    _input(tmp_path, "requirements-ci.in", "pytest==9.1.2\n")
    _input(tmp_path, "requirements-bench.in", "-c requirements-ci.txt\n")
    _input(tmp_path, "requirements-fuzz.in", "-c requirements-ci.txt\n")
    (tmp_path / "requirements-ci.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    # A deterministic resolver stand-in consumes the real ordered plan. It
    # models constraint propagation, not a network/PyPI resolution claim.
    pins: dict[str, str] = {}
    order = regeneration_order(tmp_path)
    for name in order:
        if name == "requirements-ci.in":
            (tmp_path / "requirements-ci.txt").write_text("pytest==9.1.2\n", encoding="utf-8")
        else:
            pins[name] = (tmp_path / "requirements-ci.txt").read_text(encoding="utf-8")
    CHECK.assertEqual(set(order), {"requirements-ci.in", "requirements-bench.in", "requirements-fuzz.in"})
    CHECK.assertEqual(set(pins.values()), {"pytest==9.1.2\n"})


def test_transitive_prerequisites_and_unique_outputs(tmp_path: Path) -> None:
    _input(tmp_path, "requirements-a.in", "--constraint=requirements-b.lock\n")
    _input(tmp_path, "requirements-b.in", "-crequirements-z.lock # shared\n")
    _input(tmp_path, "requirements-c.in", "--constraint requirements-z.lock\n")
    _input(tmp_path, "requirements-z.in")
    order = regeneration_order(tmp_path)
    CHECK.assertEqual(len(order), 4)
    CHECK.assertLess(order.index("requirements-z.in"), order.index("requirements-b.in"))
    CHECK.assertLess(order.index("requirements-b.in"), order.index("requirements-a.in"))
    CHECK.assertLess(order.index("requirements-z.in"), order.index("requirements-c.in"))


@pytest.mark.parametrize("directive", [
    "-c requirements-missing.lock", "-c ../requirements-ci.txt",
    "-c /requirements-ci.txt", "-c https://example.test/constraints.lock",
    "-c requirements-ci.csv", "-c", "--constraint=", "-c a.lock b.lock",
])
def test_unsupported_or_missing_constraints_fail_before_resolution(tmp_path: Path, directive: str) -> None:
    _input(tmp_path, "requirements-bench.in", directive)
    with pytest.raises(ValueError):
        regeneration_order(tmp_path)


@pytest.mark.parametrize("self_cycle", [False, True])
def test_cycle_is_an_error_not_partial_output(tmp_path: Path, self_cycle: bool) -> None:
    target = "a" if self_cycle else "b"
    _input(tmp_path, "requirements-a.in", f"-c requirements-{target}.lock\n")
    _input(tmp_path, "requirements-b.in", "-c requirements-a.lock\n")
    with pytest.raises(ValueError, match="cycle"):
        regeneration_order(tmp_path)


def test_unconstrained_inputs_are_deterministic_and_empty_is_empty(tmp_path: Path) -> None:
    CHECK.assertEqual(regeneration_order(tmp_path), [])
    _input(tmp_path, "requirements-z.in", "# -c ignored.lock\ndep==1\n")
    _input(tmp_path, "requirements-a.in", "dep==2\n")
    CHECK.assertEqual(regeneration_order(tmp_path), ["requirements-a.in", "requirements-z.in"])


@pytest.mark.parametrize("target", ["requirements-ci.lock", "requirements-runtime.txt"])
def test_existing_input_does_not_make_a_noncanonical_output_valid(tmp_path, target):
    _input(tmp_path, "requirements-ci.in", "dep==1")
    _input(tmp_path, "requirements-runtime.in", "dep==1")
    _input(tmp_path, "requirements-consumer.in", "-c " + target)
    with pytest.raises(ValueError, match="noncanonical"):
        regeneration_order(tmp_path)
