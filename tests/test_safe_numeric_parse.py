"""v4.44.0 tests for the safe_float / safe_int helpers.

Closes semgrep nan-injection findings on HTTP-handler numeric
parsing: pre-v4.44.0 code did ``float(request.query.get(...))``
which happily accepts ``NaN``/``+/-Inf``, breaking any
downstream ordering-based guard.
"""
from __future__ import annotations

import math

import pytest

from arena.handler_helpers import safe_float, safe_int


# ---------------------------------------------------------------------------
# safe_float -- happy path
# ---------------------------------------------------------------------------
def test_safe_float_parses_ordinary_number():
    assert safe_float("1.5", default=0.0) == 1.5


def test_safe_float_accepts_negative_and_zero():
    assert safe_float("-0.5", default=0.0) == -0.5
    assert safe_float("0", default=1.0) == 0.0


def test_safe_float_int_input_ok():
    assert safe_float(3, default=0.0) == 3.0


# ---------------------------------------------------------------------------
# safe_float -- the security payload: NaN and Inf
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "nan", "NaN", "NAN", "Nan",
    "inf", "Inf", "INF", "+inf", "-inf",
    "infinity", "-Infinity",
    float("nan"), float("inf"), float("-inf"),
])
def test_safe_float_rejects_non_finite_with_default(bad):
    """Every NaN/Inf shape falls back to the default. Pre-fix
    code passed these through and the downstream ordering
    check silently returned False for both branches."""
    assert safe_float(bad, default=1.5) == 1.5


@pytest.mark.parametrize("bad", ["nan", "inf", float("nan"), float("inf")])
def test_safe_float_rejects_non_finite_without_default_raises(bad):
    with pytest.raises(ValueError):
        safe_float(bad)


# ---------------------------------------------------------------------------
# safe_float -- clamping
# ---------------------------------------------------------------------------
def test_safe_float_clamps_to_minimum():
    assert safe_float("0.001", default=1.0, minimum=0.05) == 0.05


def test_safe_float_clamps_to_maximum():
    assert safe_float("100.0", default=1.0, maximum=30.0) == 30.0


def test_safe_float_within_range_passes_through():
    assert safe_float("2.5", default=1.0, minimum=0.05, maximum=30.0) == 2.5


def test_safe_float_out_of_range_without_default_raises():
    with pytest.raises(ValueError):
        safe_float("100.0", minimum=0.0, maximum=30.0)


# ---------------------------------------------------------------------------
# safe_float -- garbage input
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "abc", "1.5.6", None, [], {}, object()])
def test_safe_float_rejects_garbage_with_default(bad):
    assert safe_float(bad, default=42.0) == 42.0


def test_safe_float_rejects_garbage_without_default_raises():
    with pytest.raises((ValueError, TypeError)):
        safe_float("abc")


# ---------------------------------------------------------------------------
# safe_float -- return value is really finite
# ---------------------------------------------------------------------------
def test_safe_float_output_is_finite():
    """Sanity: no code path returns NaN/Inf even when we
    default-back to a NaN-looking string. The default itself
    should be a normal number picked by the caller."""
    out = safe_float("nan", default=1.5)
    assert math.isfinite(out)


# ---------------------------------------------------------------------------
# safe_int
# ---------------------------------------------------------------------------
def test_safe_int_parses_ordinary():
    assert safe_int("42", default=0) == 42


def test_safe_int_rejects_float_string_with_default():
    """Python's int() rejects '1.5' -- we fall to default."""
    assert safe_int("1.5", default=10) == 10


def test_safe_int_clamps():
    assert safe_int("-5", default=0, minimum=0) == 0
    assert safe_int("1000000", default=100, maximum=100) == 100


def test_safe_int_rejects_garbage_with_default():
    assert safe_int("abc", default=7) == 7


def test_safe_int_no_default_raises_on_bad():
    with pytest.raises((ValueError, TypeError)):
        safe_int("abc")
