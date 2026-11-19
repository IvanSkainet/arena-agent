"""Output accounting remains independent for stdout/stderr across truncation."""
from arena.exec.runner import _decode_limited, _StreamBudget


def test_stream_budget_counts_discarded_bytes_without_starving_other_stream():
    budget = _StreamBudget(4)
    assert budget.consume("stdout", b"abc") == {"type": "stdout", "data": b"abc"}
    assert budget.consume("stdout", b"def") == {"type": "stdout", "data": b"d"}
    assert budget.consume("stdout", b"more") is None
    assert budget.consume("stderr", b"err!") == {"type": "stderr", "data": b"err!"}
    assert budget.totals == {"stdout": 10, "stderr": 4}
    assert budget.truncated is True


def test_exact_stream_budget_is_not_truncated_until_an_extra_byte_arrives():
    budget = _StreamBudget(3)
    assert budget.consume("stdout", b"abc") == {"type": "stdout", "data": b"abc"}
    assert budget.truncated is False
    assert budget.consume("stdout", b"x") is None
    assert budget.truncated is True


def test_buffered_budget_preserves_utf8_replacement_boundary_and_empty_decoder_contract():
    def forbidden(_data):
        raise AssertionError("empty output must not call the decoder")

    assert _decode_limited(b"", forbidden, 3) == ("", False)
    assert _decode_limited(b"raw", lambda _: "éé", 3) == ("é�", True)
    assert _decode_limited(b"raw", lambda _: "éé", 4) == ("éé", False)
