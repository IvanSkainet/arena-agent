"""FIFO delivery must not depend on how fast the clock ticks (#179).

`send_message` names inbox files and `claim_next` delivers them in
`sorted()` order, so the filename *is* the ordering contract. It used to be
`f"{created_at:015.4f}"` -- 0.1 ms resolution -- followed by a uuid4. Two
messages inside one tick tied on the timestamp and the sort fell through to
the uuid, which is random. FIFO by luck.

Measured before the fix, against the real store:

    6 sends x 300 trials: 244 ok / 56 fail          (18.7%)
    the shipped test, 60 pytest runs: 3 failures    (5%)

Why it hid on Windows: not a coarser clock. `time.time_ns()` resolves to
100 ns there and 123 ns on Linux -- the *format* discarded that. A send costs
~0.097 ms on the Linux sandbox against a 0.1 ms tick, so collisions were
constant, while the slower Windows filesystem spaced sends past the tick.
Windows was never safe, only slow. Conversely `time.time_ns()` returns
duplicate values under concurrency on Windows (7.08% of 20000 calls across 8
threads, versus 0% on Linux), which is why nanoseconds alone are not enough
and a monotonic counter breaks the remaining ties.

These tests assert the invariant with the clock held still, so they cannot be
satisfied by a machine that merely happens to be fast enough.
"""

from __future__ import annotations

import itertools
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.relay import (  # noqa: E402
    lifecycle as L,
    ordering as O,
    store as S,
)

FROZEN_NS = 1_700_000_000_000_000_000


@pytest.fixture(autouse=True)
def _reset_sequence():
    """Each test starts from a known counter value."""
    original = O._SEQUENCE
    O._SEQUENCE = itertools.count()
    yield
    O._SEQUENCE = original


@pytest.fixture
def frozen_clock(monkeypatch):
    """Every send reports the same nanosecond.

    This is the whole point of the fix: ordering has to hold when the clock
    cannot separate two messages. A test that relies on real time passing
    would pass on the old code too, whenever the machine was slow enough.
    """
    monkeypatch.setattr(S.time, "time_ns", lambda: FROZEN_NS)


def test_fifo_holds_when_every_send_shares_one_nanosecond(tmp_path, frozen_clock):
    for i in range(10):
        S.send_message(tmp_path, f"m{i}")
    delivered = [S.claim_next(tmp_path).body for _ in range(10)]
    assert delivered == [f"m{i}" for i in range(10)]


def test_replies_are_also_ordered_within_one_nanosecond(tmp_path, frozen_clock):
    """`read_replies` sorts the same way, so it needs the same guarantee.

    The original bug was fixed in `send_message` first; `post_reply` builds
    its filename identically and would otherwise have kept the defect.
    """
    sent = S.send_message(tmp_path, "question")
    S.claim_next(tmp_path)
    for i in range(6):
        S.post_reply(tmp_path, sent.id, f"answer{i}")
    bodies = [m.body for m in S.read_replies(tmp_path, consume=True)]
    assert bodies == [f"answer{i}" for i in range(6)]


def test_the_ordering_prefix_never_repeats_within_a_nanosecond():
    seen = {O.ordering_prefix(FROZEN_NS) for _ in range(5000)}
    assert len(seen) == 5000


def test_the_prefix_ascends_under_concurrent_senders(frozen_clock):
    """Threads must not interleave into a non-monotonic sequence."""
    produced: list[str] = []
    lock = threading.Lock()

    def worker():
        local = [O.ordering_prefix(FROZEN_NS) for _ in range(200)]
        with lock:
            produced.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(produced)) == len(produced)


def test_the_sequence_never_wraps_into_a_smaller_string():
    """A masked counter inverts ordering the moment it rolls over.

    The first version of this fix used `seq % 1_000_000`, and `999999` sorts
    after `000000` as text -- so the millionth message would have jumped the
    queue. Caught by asserting the wrap instead of arguing it was
    unreachable.
    """
    O._SEQUENCE = itertools.count(999_998)
    prefixes = [O.ordering_prefix(FROZEN_NS) for _ in range(3)]
    assert prefixes == sorted(prefixes)


def test_exhausting_the_sequence_refuses_instead_of_reordering():
    """Past 12 digits the field widens and lexical order breaks.

    Unreachable in practice -- ~31 years at a thousand messages a second --
    but an unchecked assumption is how ordering inverts once, years later,
    with nobody able to reproduce it. Failing loudly is recoverable; a
    silently reordered mailbox is not.
    """
    O._SEQUENCE = itertools.count(O.SEQUENCE_LIMIT - 1)
    O.ordering_prefix(FROZEN_NS)  # the last valid one
    with pytest.raises(RuntimeError, match="sequence exhausted"):
        O.ordering_prefix(FROZEN_NS)


def test_a_mailbox_written_by_the_old_format_still_drains_in_order(tmp_path):
    """Upgrading with a non-empty inbox must not reorder what is queued.

    The legacy name is `{created_at:015.4f}-<id>.json`. At an equal second it
    sorts before a new name because '.' precedes any digit; otherwise the
    seconds field decides. Both are exercised here by writing legacy files
    that are genuinely older, as a real upgrade would leave them.

    An earlier version of this test wrote the legacy files at `base + i` with
    `base = time.time()`, i.e. in the *future* relative to the new sends, and
    then blamed the format when they interleaved. The fixture was wrong, not
    the code -- noted because the false conclusion briefly reached a comment
    in `store.py`.
    """
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    base = time.time() - 10  # genuinely older, as a real upgrade would be
    for i in range(3):
        legacy = {
            "id": f"{i:012x}",
            "body": f"old{i}",
            "sender": "operator",
            "created_at": base + i,
            "meta": {},
            "lifecycle": "queued",
        }
        (inbox / f"{base + i:015.4f}-{i:012x}.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )

    for i in range(3):
        S.send_message(tmp_path, f"new{i}")

    delivered = [S.claim_next(tmp_path).body for _ in range(6)]
    assert delivered == ["old0", "old1", "old2", "new0", "new1", "new2"]

    # And the equal-second boundary, which the drain above does not reach:
    # a legacy file stamped at the same second as a new one must still come
    # first, because '.' sorts before any digit at that offset.
    now_ns = time.time_ns()
    seconds = now_ns // 1_000_000_000
    legacy_same_second = f"{seconds + 0.0001:015.4f}-{'a' * 12}.json"
    fresh = f"{O.ordering_prefix(now_ns)}-{'b' * 12}.json"
    assert legacy_same_second < fresh


def test_the_filename_still_ends_with_the_message_id(tmp_path, frozen_clock):
    """`lifecycle` finds claimed messages by globbing `*-<id>.json`.

    Any future change to the ordering prefix has to keep the id last, or
    reply routing breaks in a way the ordering tests would not notice.
    """
    sent = S.send_message(tmp_path, "hello")
    S.claim_next(tmp_path)
    found = L._claimed_message_path(tmp_path, sent.id)
    assert found is not None
    assert found.name.endswith(f"-{sent.id}.json")


def test_created_at_matches_the_name_it_is_sorted_by(tmp_path):
    """The record and the filename must come from one clock reading.

    Two separate reads would let a message sort ahead of its own timestamp,
    which turns any later audit of the mailbox into fiction.
    """
    sent = S.send_message(tmp_path, "hello")
    name = next((tmp_path / "inbox").glob("*.json")).name
    seconds, _, rest = name.partition(".")
    nanoseconds = rest.split("-")[0]
    from_name = int(seconds) + int(nanoseconds) / 1_000_000_000
    assert from_name == pytest.approx(sent.created_at, abs=1e-6)


def test_a_legacy_name_that_rounded_up_still_sorts_before_a_later_message(tmp_path):
    """`{x:015.4f}` rounds to nearest, so a legacy name can overshoot.

    Raised in review of PR #180 and confirmed: my claim that the two formats
    compared safely assumed truncation, and `%f` does not truncate. A legacy
    message at `...446.000050068` is *named* `...446.0001` -- 49.8 us late --
    so a new message sent 1 us afterwards sorted ahead of it and was
    delivered first. Reproduced end to end before fixing.

    Delivery order therefore keys off the earliest instant a name can
    represent, not the name itself.
    """
    legacy_true = 1787639446.000050068
    assert float(f"{legacy_true:015.4f}") > legacy_true, "fixture must round up"

    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    (inbox / f"{legacy_true:015.4f}-{'a' * 12}.json").write_text(
        json.dumps(
            {
                "id": "a" * 12,
                "body": "old_sent_first",
                "sender": "operator",
                "created_at": legacy_true,
                "meta": {},
                "lifecycle": "queued",
            }
        ),
        encoding="utf-8",
    )

    original = S.time.time_ns
    S.time.time_ns = lambda: int(legacy_true * 1_000_000_000) + 1_000
    try:
        S.send_message(tmp_path, "new_sent_second")
    finally:
        S.time.time_ns = original

    delivered = [S.claim_next(tmp_path).body for _ in range(2)]
    assert delivered == ["old_sent_first", "new_sent_second"]


@pytest.mark.parametrize("overshoot_ns", [1_000, 10_000, 49_000, 60_000])
def test_legacy_and_new_stay_ordered_across_the_rounding_grid(tmp_path, overshoot_ns):
    """One hand-picked timestamp proves little; sweep the bucket instead."""
    legacy_true = 1787639446.000050068
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    (inbox / f"{legacy_true:015.4f}-{'a' * 12}.json").write_text(
        json.dumps(
            {
                "id": "a" * 12,
                "body": "old",
                "sender": "operator",
                "created_at": legacy_true,
                "meta": {},
                "lifecycle": "queued",
            }
        ),
        encoding="utf-8",
    )
    original = S.time.time_ns
    S.time.time_ns = lambda: int(legacy_true * 1_000_000_000) + overshoot_ns
    try:
        S.send_message(tmp_path, "new")
    finally:
        S.time.time_ns = original

    assert [S.claim_next(tmp_path).body for _ in range(2)] == ["old", "new"]
