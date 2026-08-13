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
import os
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


def test_unfinished_atomic_file_never_matches_mailbox_json_glob(root, monkeypatch):
    """Windows readers must not open the temp file before os.replace.

    Live repair E2E reproduced WinError 32 twice: `_write_atomic` created
    `.tmp-*.json`, the terminal reply long-poll included it in `glob('*.json')`,
    and Windows refused to replace the still-open source.  The temp suffix is
    part of the concurrency contract, not cosmetic naming.
    """
    real_replace = S.os.replace
    observed: list[Path] = []

    def checked_replace(src, dst):
        source = Path(src)
        observed.append(source)
        assert source.suffix != ".json"
        assert not source.match("*.json")
        return real_replace(src, dst)

    monkeypatch.setattr(S.os, "replace", checked_replace)
    S.send_message(root, "not visible until committed")
    assert observed and observed[0].suffix == ".partial"
    monkeypatch.setattr(S.os, "replace", real_replace)
    assert S.claim_next(root).body == "not visible until committed"


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
    assert S.prune(root) == {"removed": 0, "failed": 0, "remaining": 0}


def test_prune_reports_files_it_could_not_delete(root):
    """Windows raises PermissionError for anything still held open.

    The first version counted only successes, so a pass that deleted 5 of
    10 and failed on the rest reported "removed: 5" and looked clean. A
    housekeeping report that overstates itself is the token-note problem
    from bug #66 in a quieter place.
    """
    import os
    import pathlib as _pl

    for i in range(6):
        S.send_message(root, f"m{i}")
        S.claim_next(root)
    for path in (root / "claimed").glob("*"):
        os.utime(path, (0, 0))

    real_unlink = _pl.Path.unlink
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] % 2:
            raise PermissionError("file in use by another process")
        return real_unlink(self, *a, **k)

    _pl.Path.unlink = flaky
    try:
        result = S.prune(root, keep_recent=0)
    finally:
        _pl.Path.unlink = real_unlink

    assert result["failed"] > 0, "undeletable files were not reported"
    on_disk = len(list((root / "claimed").glob("*")))
    assert result["remaining"] == on_disk, (
        f"reported {result['remaining']} remaining, {on_disk} actually there"
    )


def test_prune_never_raises_when_the_filesystem_says_no(root):
    """Housekeeping must not turn a working send into a 500."""
    import os
    import pathlib as _pl

    S.send_message(root, "m")
    S.claim_next(root)
    for path in (root / "claimed").glob("*"):
        os.utime(path, (0, 0))

    real_unlink = _pl.Path.unlink
    _pl.Path.unlink = lambda self, *a, **k: (_ for _ in ()).throw(
        PermissionError("locked"))
    try:
        result = S.prune(root, keep_recent=0)
    finally:
        _pl.Path.unlink = real_unlink
    assert result["removed"] == 0
    assert result["failed"] >= 1


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


def test_concurrent_reply_readers_never_see_the_same_reply_twice(tmp_path):
    """Bug #73: the operator's direction had the duplicate-delivery bug.

    `claim_next` was hardened in v4.166.0 after Windows CI reported
    `lost -29` -- a negative loss, i.e. duplicates. The same read-then-
    unlink shape survived in `read_replies`, untouched, because the fix
    was scoped to the agent's side of the mailbox. Two operator consoles
    long-polling `/v1/relay/replies`, or a console plus `arena-relay`,
    is enough to trigger it.

    Measured against the pre-fix code with this exact setup: 300 replies,
    16 threads, **542 deliveries and 96 duplicates**. The assertion is on
    duplicates, not on losses, because a duplicated answer misleads the
    operator while a lost one merely makes them ask again.
    """
    import collections
    import threading

    total = 300
    for i in range(total):
        msg = S.send_message(tmp_path, f"question {i}")
        S.post_reply(tmp_path, msg.id, f"answer {i}")

    seen: collections.Counter = collections.Counter()
    lock = threading.Lock()

    def drain():
        while True:
            batch = S.read_replies(tmp_path, consume=True)
            if not batch:
                return
            with lock:
                for reply in batch:
                    seen[reply.id] += 1

    workers = [threading.Thread(target=drain) for _ in range(16)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    duplicated = {rid: n for rid, n in seen.items() if n > 1}
    assert not duplicated, f"{len(duplicated)} replies delivered more than once"
    assert sum(seen.values()) == total
    assert len(seen) == total, f"lost {total - len(seen)} replies"


def test_counting_replies_does_not_eat_them(tmp_path):
    """Reverse sabotage for #73.

    The fix deletes before delivering, so the obvious way to get it wrong
    is to delete on the counting path too -- `/v1/relay/status` calls
    `read_replies(consume=False)` on every status poll, and a status
    endpoint that silently drains the operator's inbox would be a far
    worse bug than the one being fixed.
    """
    msg = S.send_message(tmp_path, "question")
    S.post_reply(tmp_path, msg.id, "answer")

    for _ in range(5):
        assert len(S.read_replies(tmp_path, consume=False)) == 1

    consumed = S.read_replies(tmp_path, consume=True)
    assert [m.body for m in consumed] == ["answer"]
    assert S.read_replies(tmp_path, consume=False) == []


def test_the_claim_survives_a_delete_that_does_not_remove_the_name(tmp_path,
                                                                   monkeypatch):
    """Bug #75: the #73 fix was POSIX-only, and CI had to tell us.

    v4.166.2 claimed a reply with `os.unlink`, reasoning that exactly one
    caller can succeed at removing a path. True on POSIX. **False on
    Windows**, where a delete flags the file and the directory entry
    survives until the last handle closes -- so two threads both see
    `unlink` return cleanly and both deliver the reply. The Windows and
    macOS matrix reported *15 replies delivered more than once* while
    Linux stayed green, which is exactly why local preflight passed it.

    This test makes that platform behaviour reproducible on Linux: it
    replaces the removal with a no-op, simulating the worst case where a
    delete reports success and removes nothing at all. Under that
    filesystem the claim must still be exclusive, because the claim is a
    rename to a unique name rather than a delete.

    Without this, the only detector for the next instance is CI, and CI
    told us after the release was already tagged and shipped.
    """
    import collections
    import threading

    total = 120
    for index in range(total):
        msg = S.send_message(tmp_path, f"question {index}")
        S.post_reply(tmp_path, msg.id, f"answer {index}")

    real_unlink = os.unlink

    def unlink_that_does_not_remove(path, *args, **kwargs):
        # Windows: "deleted" but the name is still there.
        return None

    monkeypatch.setattr(os, "unlink", unlink_that_does_not_remove)

    seen: collections.Counter = collections.Counter()
    lock = threading.Lock()

    def drain():
        for _ in range(40):
            batch = S.read_replies(tmp_path, consume=True)
            if not batch:
                return
            with lock:
                for reply in batch:
                    seen[reply.id] += 1

    workers = [threading.Thread(target=drain) for _ in range(12)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    monkeypatch.setattr(os, "unlink", real_unlink)

    duplicated = {rid: n for rid, n in seen.items() if n > 1}
    assert not duplicated, (
        f"{len(duplicated)} replies delivered twice when unlink does not "
        f"remove the name -- the claim depends on POSIX delete semantics")
    assert len(seen) == total, f"lost {total - len(seen)} replies"


def test_claim_markers_are_never_left_behind(tmp_path):
    """The rename-based claim must not litter.

    The claim moves the reply to a `.taken` name before removing it. If
    the removal is skipped or the name is reused, the replies directory
    fills with debris and `inbox_depth`-style counts start lying.
    """
    for index in range(25):
        msg = S.send_message(tmp_path, f"q{index}")
        S.post_reply(tmp_path, msg.id, f"a{index}")

    assert len(S.read_replies(tmp_path, consume=True)) == 25
    assert S.read_replies(tmp_path, consume=False) == []

    leftovers = [p.name for p in (tmp_path / "replies").iterdir()]
    assert leftovers == [], f"claim debris left behind: {leftovers}"


def test_the_claim_tombstone_is_never_recycled(tmp_path):
    """#75, the property no Linux runtime test can trip over.

    The claim is an `O_EXCL` lock in `claimed/`. The lock must **outlive**
    the delivery: a marker that gets removed frees its own name, and the
    next reader to encounter the same reply name creates it again and
    delivers a second copy. That is precisely how the v4.166.4 draft --
    `O_EXCL` plus an immediate unlink of the marker -- reintroduced
    duplicates.

    On Linux the reply file disappears fast enough that the window is
    hard to hit, so the ordering is asserted directly instead of raced.
    Three sabotage runs showed the concurrency tests alone cannot see it
    here; Windows CI could, twice, after the tag was already pushed.
    """
    msg = S.send_message(tmp_path, "question")
    S.post_reply(tmp_path, msg.id, "answer")
    replies_dir = tmp_path / "replies"
    reply_name = next(replies_dir.glob("*.json")).name

    assert [m.body for m in S.read_replies(tmp_path, consume=True)] == ["answer"]

    claimed = tmp_path / "claimed"
    markers = [p.name for p in claimed.iterdir()]
    assert markers, (
        "the claim left no tombstone in claimed/; a claim that cleans up "
        "after itself can be re-acquired for the same reply")
    assert any(reply_name in name for name in markers), (
        f"tombstone does not identify the reply it claimed: {markers}")

    # And the reply itself is gone, so nothing is served twice.
    assert S.read_replies(tmp_path, consume=False) == []
    assert list(replies_dir.glob("*.json")) == []


def test_a_reply_whose_tombstone_exists_is_never_delivered(tmp_path):
    """The tombstone must actually be honoured, not merely written.

    Simulates the crash case: a reader claimed a reply and died before
    removing the file. The lock is on disk, the reply file is still
    there. Delivering it now would be the duplicate this whole fix
    exists to prevent.
    """
    msg = S.send_message(tmp_path, "question")
    S.post_reply(tmp_path, msg.id, "answer")
    reply_file = next((tmp_path / "replies").glob("*.json"))

    lock = tmp_path / "claimed" / (reply_file.name + ".reply.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("", encoding="utf-8")

    assert S.read_replies(tmp_path, consume=True) == [], (
        "a reply with an existing tombstone was delivered anyway")
