"""The operator <-> agent mailbox.

Born from a Discord thread: the tunnel already carries data both ways, so
why type at the agent in a browser tab instead of a terminal?

The part that cannot be built is worth stating in a test file, because a
future maintainer will be tempted: **an Arena session cannot be started
from this side.** arena.ai has no public API, and its Terms of Use forbid
access "through programmatic or automated means" (§5(vi)) and the use of
"spiders, robots, scrapers, crawlers, avatars" against the Service
(§5(vii)). A headless browser driving the site would breach both, break
on any redesign, and put the operator's account at risk.

So this is a mailbox with an optional wait, and the honesty requirement
falls out of that: `send` must not imply anyone is listening when nobody
is. Claiming delivery to nobody is the same class of lie as the
token-rotation note in bug #66.

`arena/tasks/queue.py` was deliberately not reused. Verified against the
live bridge: posting a plain sentence to `/v1/tasks` came back as
`state: failed, exit_code: 1`, because the runner tried to execute the
sentence as a shell command. Prose needs its own channel.
"""
from __future__ import annotations

import collections
import json
import threading
from pathlib import Path

import pytest

from arena.relay import store as S


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "relay"


# --------------------------------------------------------------------
# Round trip.
# --------------------------------------------------------------------

def test_a_message_survives_the_round_trip(root):
    sent = S.send_message(root, "проверь CI")
    assert S.inbox_depth(root) == 1

    claimed = S.claim_next(root)
    assert claimed is not None
    assert claimed.id == sent.id
    assert claimed.body == "проверь CI"
    assert S.inbox_depth(root) == 0, "a claimed message must leave the inbox"

    S.post_reply(root, claimed.id, "готово, 35/35")
    replies = S.read_replies(root, in_reply_to=claimed.id)
    assert [r.body for r in replies] == ["готово, 35/35"]


def test_claiming_twice_returns_nothing(root):
    S.send_message(root, "one")
    assert S.claim_next(root) is not None
    assert S.claim_next(root) is None


def test_replies_are_consumed_by_default(root):
    msg = S.send_message(root, "q")
    S.post_reply(root, msg.id, "a")
    assert len(S.read_replies(root, in_reply_to=msg.id)) == 1
    assert S.read_replies(root, in_reply_to=msg.id) == []


def test_replies_can_be_read_without_consuming(root):
    msg = S.send_message(root, "q")
    S.post_reply(root, msg.id, "a")
    assert len(S.read_replies(root, in_reply_to=msg.id, consume=False)) == 1
    assert len(S.read_replies(root, in_reply_to=msg.id, consume=False)) == 1


def test_replies_are_filtered_by_conversation(root):
    a = S.send_message(root, "first")
    b = S.send_message(root, "second")
    S.post_reply(root, a.id, "answer to A")
    S.post_reply(root, b.id, "answer to B")
    assert [r.body for r in S.read_replies(root, in_reply_to=a.id)] == ["answer to A"]
    assert [r.body for r in S.read_replies(root, in_reply_to=b.id)] == ["answer to B"]


def test_messages_come_back_in_order(root):
    for i in range(6):
        S.send_message(root, f"m{i}")
    assert [S.claim_next(root).body for _ in range(6)] == [f"m{i}" for i in range(6)]


# --------------------------------------------------------------------
# The property that matters most: no message delivered twice.
# --------------------------------------------------------------------

def test_concurrent_claims_never_duplicate_a_message(root):
    """Two agent sessions polling at once must not both get the same text.

    A duplicated instruction is worse than a lost one -- "delete the
    branch" executed twice is a different outcome than executed once.
    `claim_next` relies on os.rename being atomic; this is the test that
    says so out loud.
    """
    # 120 messages / 8 threads passed on Linux while the Windows matrix
    # was failing with "lost -29" -- duplicates, not losses. Wider and
    # busier, plus a barrier so every thread starts inside the same glob
    # window instead of politely queueing behind the first one.
    total = 400
    for i in range(total):
        S.send_message(root, f"m{i}")

    seen: list[str] = []
    lock = threading.Lock()

    def worker():
        while True:
            msg = S.claim_next(root)
            if msg is None:
                return
            with lock:
                seen.append(msg.body)

    workers = 16
    barrier = threading.Barrier(workers)

    def synced_worker():
        barrier.wait()
        worker()

    threads = [threading.Thread(target=synced_worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    duplicates = [b for b, n in collections.Counter(seen).items() if n > 1]
    assert not duplicates, (
        f"{len(duplicates)} message(s) delivered more than once, e.g. "
        f"{duplicates[:3]} -- a duplicated instruction is worse than a lost one"
    )
    assert len(seen) == total, f"lost {total - len(seen)} message(s)"


def test_claiming_is_exclusive_even_when_the_rename_fails(root, monkeypatch):
    """The claim must not depend on the file move succeeding.

    Windows and POSIX disagree about os.rename semantics, which is what
    produced duplicate deliveries in CI. The lock file is what makes the
    claim exclusive; the move is bookkeeping. Break the move and the
    exclusivity has to hold anyway.
    """
    S.send_message(root, "only once")

    def failing_replace(src, dst):
        raise OSError("simulated cross-device move failure")

    monkeypatch.setattr(S.os, "replace", failing_replace)
    first = S.claim_next(root)
    second = S.claim_next(root)
    assert first is not None and first.body == "only once"
    assert second is None, "the same message was handed out twice"


# --------------------------------------------------------------------
# Input validation -- fail closed, say why.
# --------------------------------------------------------------------

@pytest.mark.parametrize("body", ["", "   ", "\n\t ", None, 123, [], {}])
def test_an_empty_or_non_string_body_is_refused(root, body):
    with pytest.raises(ValueError, match="body is required"):
        S.send_message(root, body)


def test_an_oversized_message_is_refused_with_the_limit_named(root):
    with pytest.raises(ValueError) as exc:
        S.send_message(root, "x" * (S.MAX_BODY_BYTES + 1))
    assert str(S.MAX_BODY_BYTES) in str(exc.value)
    assert "/v1/fs" in str(exc.value), "tell the operator what to use instead"


def test_a_message_exactly_at_the_limit_is_accepted(root):
    """Reverse of the above: the boundary must not be off by one."""
    S.send_message(root, "x" * S.MAX_BODY_BYTES)
    assert S.inbox_depth(root) == 1


def test_multibyte_text_is_measured_in_bytes_not_characters(root):
    """Cyrillic is two bytes per character in UTF-8.

    Counting characters would let a Russian message be twice the intended
    size -- the operator writes in Russian, so this is the normal case
    here, not an edge one.
    """
    body = "я" * (S.MAX_BODY_BYTES // 2 + 1)
    assert len(body) < S.MAX_BODY_BYTES
    with pytest.raises(ValueError):
        S.send_message(root, body)


def test_a_reply_needs_both_a_target_and_a_body(root):
    with pytest.raises(ValueError):
        S.post_reply(root, "", "text")
    with pytest.raises(ValueError):
        S.post_reply(root, "abc", "")


# --------------------------------------------------------------------
# Durability.
# --------------------------------------------------------------------

def test_a_corrupt_file_does_not_jam_the_queue(root):
    """One unreadable message must not block everything behind it."""
    S.send_message(root, "good one")
    inbox = root / "inbox"
    (inbox / "0000000000.0000-corrupt.json").write_text("{ not json",
                                                        encoding="utf-8")
    bodies = []
    for _ in range(3):
        msg = S.claim_next(root)
        if msg is not None:
            bodies.append(msg.body)
    assert "good one" in bodies


def test_writes_are_atomic_no_partial_files_left_behind(root):
    S.send_message(root, "text")
    leftovers = list((root / "inbox").glob(".tmp-*"))
    assert leftovers == [], leftovers


def test_a_write_that_dies_midway_leaves_no_readable_message(root):
    """Sabotage found the first version of this file toothless.

    Checking only for leftover .tmp files passes even with a plain
    `open(path, "w")`, because a crash mid-write leaves a *truncated real
    file*, not a temp one -- a reader then sees a message the operator
    never finished sending. Kill the serialiser partway and assert the
    inbox is still clean.
    """
    real_dump = S.json.dump

    def dying_dump(obj, handle, **kwargs):
        handle.write('{"id": "half-writ')
        raise OSError("disk went away mid-write")

    S.json.dump = dying_dump
    try:
        with pytest.raises(OSError):
            S.send_message(root, "never finished")
    finally:
        S.json.dump = real_dump

    assert S.inbox_depth(root) == 0, "a half-written message became visible"
    assert list((root / "inbox").glob(".tmp-*")) == [], "temp file left behind"
    assert S.claim_next(root) is None


def test_claiming_moves_the_file_rather_than_deleting_it(root):
    """The claimed message must remain on disk for inspection.

    A read-and-delete implementation passes the happy-path tests but
    loses the message entirely if the agent crashes between claiming and
    acting on it. It is also not atomic, which is what
    test_concurrent_claims_never_duplicate_a_message is really about --
    that test caught the read+delete sabotage only by accident, through
    the listing assertions, so pin the mechanism directly.
    """
    S.send_message(root, "keep me")
    claimed = S.claim_next(root)
    assert claimed is not None
    on_disk = list((root / "claimed").glob("*.json"))
    assert len(on_disk) == 1, "claiming must move the file into claimed/"
    import json as _json
    assert _json.loads(on_disk[0].read_text(encoding="utf-8"))["body"] == "keep me"


def test_the_stored_file_is_valid_json_with_the_expected_shape(root):
    msg = S.send_message(root, "hello", meta={"source": "cli"})
    path = next((root / "inbox").glob("*.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["id"] == msg.id
    assert raw["body"] == "hello"
    assert raw["sender"] == "operator"
    assert raw["meta"] == {"source": "cli"}
    assert isinstance(raw["created_at"], (int, float))


# --------------------------------------------------------------------
# Waiting: driven clock, never a race.
# --------------------------------------------------------------------

def test_waiting_returns_immediately_when_a_message_is_already_there(root):
    S.send_message(root, "now")
    ticks = iter([0.0] * 50)
    msg = S.wait_for_message(root, timeout=25, now=lambda: next(ticks),
                             sleep=lambda _s: None)
    assert msg is not None and msg.body == "now"


def test_waiting_gives_up_at_the_deadline(root):
    """Driven clock so this cannot flake on a slow runner.

    The metrics staleness gate had to be rewritten for exactly this
    reason; not repeating that here.
    """
    clock = iter([0.0, 0.0, 30.0, 30.0, 30.0])
    slept: list[float] = []
    msg = S.wait_for_message(root, timeout=25, now=lambda: next(clock),
                             sleep=slept.append)
    assert msg is None
    assert slept, "it should have slept between polls rather than spinning"


def test_waiting_for_a_reply_gives_up_at_the_deadline(root):
    clock = iter([0.0, 0.0, 999.0, 999.0, 999.0])
    assert S.wait_for_reply(root, "nobody", timeout=10,
                            now=lambda: next(clock), sleep=lambda _s: None) is None


def test_a_zero_timeout_still_checks_once(root):
    """`wait=0` must mean "look now", not "do not look"."""
    S.send_message(root, "present")
    msg = S.wait_for_message(root, timeout=0, now=lambda: 0.0,
                             sleep=lambda _s: None)
    assert msg is not None


# --------------------------------------------------------------------
# Listing.
# --------------------------------------------------------------------

def test_listing_shows_which_state_each_message_is_in(root):
    S.send_message(root, "waiting")
    claimed = S.send_message(root, "will be claimed")
    S.claim_next(root)  # claims the older one ("waiting")
    S.post_reply(root, claimed.id, "answered")

    states = {m.get("state") for m in S.list_messages(root)}
    assert {"inbox", "claimed", "replies"} <= states


def test_listing_an_empty_relay_is_empty_not_an_error(root):
    assert S.list_messages(root) == []
    assert S.inbox_depth(root) == 0


def test_the_claim_uses_an_exclusive_create_not_a_rename():
    """Pin the mechanism, because the race only reproduces on Windows.

    Sabotage proved the behavioural test is not enough: swapping the lock
    file back for a bare `os.rename` keeps every assertion above green on
    Linux, where rename happens to behave. CI on Windows disagreed --
    `lost -29 message(s)`, a negative count, meaning duplicate delivery.

    `os.open(..., O_CREAT | O_EXCL)` is the one primitive both platforms
    define identically: it fails if the file exists. That is what the
    claim rests on now, so that is what this asserts.
    """
    import ast
    import pathlib

    source = pathlib.Path(S.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    claim = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "claim_next")
    body = ast.dump(claim)

    assert "O_EXCL" in body, (
        "claim_next no longer takes an exclusive lock; on Windows a plain "
        "rename delivered the same message to two claimers"
    )
    assert "'rename'" not in body, (
        "os.rename is back in claim_next -- use os.replace, which is "
        "defined to overwrite on both platforms"
    )


# --------------------------------------------------------------------
# Housekeeping. Added before the release, after measuring what a month
# of use leaves behind: 500 messages read and answered -> 1000 files in
# claimed/, and nothing anywhere removed any of them.
# --------------------------------------------------------------------

def test_claimed_messages_are_pruned_once_they_are_old(root):
    import os
    import time as _t

    for i in range(400):
        S.send_message(root, f"m{i}")
        S.claim_next(root)
    aged = _t.time() - 30 * 86400
    for path in (root / "claimed").glob("*"):
        os.utime(path, (aged, aged))

    before = len(list((root / "claimed").glob("*")))
    result = S.prune(root, keep_recent=50)
    after = len(list((root / "claimed").glob("*")))
    assert before > after, "prune removed nothing"
    assert result["removed"] == before - after
    assert after == 50, "the keep_recent floor was not honoured"


def test_recent_messages_survive_even_when_old(root):
    """A burst must not age everything out and leave nothing to inspect."""
    import os
    import time as _t

    for i in range(20):
        S.send_message(root, f"m{i}")
        S.claim_next(root)
    aged = _t.time() - 365 * 86400
    for path in (root / "claimed").glob("*"):
        os.utime(path, (aged, aged))

    S.prune(root, older_than_seconds=1, keep_recent=10)
    assert len(list((root / "claimed").glob("*"))) == 10


def test_prune_never_touches_unread_messages(root):
    """Deleting inbox/ on a timer would discard the operator's words.

    That is the one failure this whole channel exists to prevent, so it
    gets its own test rather than relying on the implementation staying
    obvious.
    """
    import os
    import time as _t

    S.send_message(root, "nobody has read this yet")
    aged = _t.time() - 365 * 86400
    for path in (root / "inbox").glob("*"):
        os.utime(path, (aged, aged))

    S.prune(root, older_than_seconds=1, keep_recent=0)
    assert S.inbox_depth(root) == 1, "an unread message was deleted by housekeeping"
    assert S.claim_next(root).body == "nobody has read this yet"


def test_prune_leaves_fresh_messages_alone(root):
    for i in range(5):
        S.send_message(root, f"m{i}")
        S.claim_next(root)
    before = len(list((root / "claimed").glob("*")))
    assert S.prune(root, keep_recent=0)["removed"] == 0
    assert len(list((root / "claimed").glob("*"))) == before


def test_prune_on_an_empty_relay_is_not_an_error(root):
    assert S.prune(root) == {"removed": 0, "remaining": 0}


def test_the_http_layer_calls_prune_on_ordinary_traffic():
    """A prune() nobody calls is a button nobody presses.

    The relay has no background loop, so housekeeping rides on normal
    requests. Asserting the wiring because the alternative is discovering
    in six months that claimed/ has 40k files in it.
    """
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1]
              / "arena" / "relay" / "handlers.py").read_text(encoding="utf-8")
    assert "store.prune" in source, "handlers never call prune"
    tree = ast.parse(source)
    names = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "prune" in names
