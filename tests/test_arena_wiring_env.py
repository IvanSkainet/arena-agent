"""v4.76.0 coverage expansion: tests for arena/wiring/env.py.

v4.76.0 is the second step of the coverage-gate
gradual-tightening plan (v4.74.0 → 51% → v4.76.0 → 55%
on Linux, 50% on Windows). The first step covered
``arena.util`` (small, pure, stdlib-only helpers).
The second step covers ``arena/wiring/env.py``
(also small, also pure).

``RuntimeEnv`` is a simple attribute-access wrapper
for runtime composition values. The class has only
two public methods: ``__init__`` (stores the values
mapping) and ``__getattr__`` (returns the value or
raises ``AttributeError``). The class is at 82%
coverage (2 missing statements out of 11 lines); the
new tests bring it to ~100%.

The class is small enough that the tests cover every
public behaviour:

* Construction with an empty dict (the empty-env case).
* Construction with a non-empty dict and a successful
  attribute read.
* Missing-attribute read raises ``AttributeError``
  (not ``KeyError`` — the wrapper's contract is that
  the caller sees ``AttributeError`` so the wrapper is
  a drop-in for a regular Python object).
* The wrapper's ``__getattr__`` is only called for
  attributes that don't exist (Python's normal
  attribute lookup is used for attributes that do
  exist, including dunder methods).
"""
from __future__ import annotations

import pytest

from arena.wiring.env import RuntimeEnv


def test_runtime_env_empty_construction() -> None:
    """An empty RuntimeEnv can be constructed; attribute reads on it raise AttributeError."""
    env = RuntimeEnv({})
    with pytest.raises(AttributeError):
        env.anything  # noqa: B018


def test_runtime_env_attribute_read() -> None:
    """RuntimeEnv returns values from the underlying mapping on attribute read."""
    env = RuntimeEnv({"name": "alice", "age": 30})
    assert env.name == "alice"
    assert env.age == 30


def test_runtime_env_missing_attribute_raises_attribute_error() -> None:
    """Missing attribute reads raise AttributeError, not KeyError.

    The wrapper's contract: callers see AttributeError
    so the wrapper is a drop-in for a regular Python
    object. The wrapper must convert the internal
    KeyError to AttributeError.
    """
    env = RuntimeEnv({"name": "alice"})
    with pytest.raises(AttributeError) as exc_info:
        env.missing  # noqa: B018
    # The exception message includes the missing
    # attribute name (Python's standard AttributeError
    # behaviour); we just check the type.
    assert "missing" in str(exc_info.value) or str(exc_info.value) == "missing"


def test_runtime_env_does_not_break_dunder_access() -> None:
    """Dunder attributes (e.g. __class__) still work via Python's normal lookup.

    The wrapper's ``__getattr__`` is only called for
    attributes that don't exist via the normal lookup
    chain. So ``env.__class__`` should return the
    class, not raise ``AttributeError``.
    """
    env = RuntimeEnv({"name": "alice"})
    assert env.__class__ is RuntimeEnv


def test_runtime_env_supports_nested_mappings() -> None:
    """RuntimeEnv stores the mapping by reference; nested values are accessible."""
    nested = {"level1": {"level2": "deep"}}
    env = RuntimeEnv(nested)
    # env.level1 returns the inner dict; the wrapper
    # doesn't recursively wrap (the contract is a
    # one-level wrapper).
    assert env.level1 == {"level2": "deep"}
    assert isinstance(env.level1, dict)  # still a plain dict, not a RuntimeEnv
