"""Delivery order for relay mailboxes (#179).

The relay stores one JSON file per message and delivers them in sorted
order, so the filename *is* the ordering contract. This module owns that
contract: how a name is built, and how names are compared.

It lives apart from `store.py` because ordering is the subtle part. The
store's job is atomic writes and exactly-once claims; getting FIFO right
turned out to need its own set of invariants, its own tests, and enough
commentary that folding it back in would push the store past the runtime
line limit for no benefit.

Background, all measured rather than assumed:

* The original name was ``f"{created_at:015.4f}-{uuid4}.json"`` -- 0.1 ms
  resolution followed by a random suffix. Two messages inside one tick tied
  on the timestamp and the sort fell through to the uuid. FIFO by luck: 56
  failures in 300 six-message trials on Linux.
* The clock was never the problem. ``time.time_ns()`` resolves to 123 ns on
  Linux and 100 ns on Windows; the format discarded that precision.
* Nanoseconds alone are still not enough. Windows returns duplicate
  ``time_ns()`` values under concurrency -- 7.08% of 20000 calls across 8
  threads, versus 0% on Linux -- so a process-local counter breaks ties.
* Legacy names cannot simply be string-compared against new ones. ``%f``
  rounds to nearest rather than truncating, so a legacy name can sit up to
  50 us *later* than the message actually was, and a new message sent inside
  that window would overtake it.
"""

from __future__ import annotations

import itertools
import threading
from pathlib import Path

#: Nanoseconds a legacy ``015.4f`` name may overshoot the true instant.
#: ``%f`` rounds to nearest, so half of the 0.1 ms bucket sits above it.
LEGACY_ROUNDING_NS = 50_000

#: Width of the fractional field in a current-format name.
NANOSECOND_DIGITS = 9

#: The counter is never wrapped -- a masked counter inverts ordering on
#: rollover, since "999999" sorts after "000000" as text. Twelve digits keep
#: the field fixed-width; passing this many messages in one process raises
#: rather than widening the field and silently reordering the mailbox.
SEQUENCE_LIMIT = 1_000_000_000_000

_SEQUENCE_LOCK = threading.Lock()
_SEQUENCE = itertools.count()



def ordering_prefix(created_ns: int) -> str:
    """Build the sortable filename prefix for a message created at ``created_ns``.

    Shape: ``<10-digit seconds>.<9-digit nanoseconds>-<12-digit counter>``.
    The decimal point sits at the same offset as the legacy format so the two
    remain comparable digit by digit.
    """
    with _SEQUENCE_LOCK:
        sequence = next(_SEQUENCE)
    if sequence >= SEQUENCE_LIMIT:
        # Widening the field would silently invert ordering, which on this
        # channel means an instruction delivered before the one that was sent
        # first. Refuse loudly: a restarted relay is recoverable, a reordered
        # mailbox is not.
        raise RuntimeError(
            f"relay ordering sequence exhausted after {SEQUENCE_LIMIT} "
            f"messages in this process; restart the relay"
        )
    seconds, nanoseconds = divmod(created_ns, 1_000_000_000)
    return f"{seconds:010d}.{nanoseconds:09d}-{sequence:012d}"


def delivery_key(path: Path) -> tuple[str, str]:
    """Sort key for a mailbox file, tolerant of the pre-#179 name format.

    Legacy names are normalised to the *earliest* instant they could
    represent, undoing the round-to-nearest they were written with. Without
    that, a legacy message queued first can be delivered second -- reproduced
    end to end: a legacy file at ``...446.000050068`` is named
    ``...446.0001``, and a new message sent 1 us later sorted ahead of it.
    """
    name = path.name
    seconds, _, rest = name.partition(".")
    fraction, _, tail = rest.partition("-")
    if not seconds.isdigit() or not fraction.isdigit():
        # Unparseable: fall back to the raw name so it still has a stable
        # position rather than crashing the drain.
        return (name, "")
    if len(fraction) == NANOSECOND_DIGITS:
        nanoseconds = int(fraction)
    else:
        widened = int(fraction.ljust(NANOSECOND_DIGITS, "0"))
        nanoseconds = max(0, widened - LEGACY_ROUNDING_NS)
    return (f"{int(seconds):010d}.{nanoseconds:09d}", tail)


def sorted_mailbox(folder: Path) -> list[Path]:
    """Mailbox files in delivery order."""
    return sorted(folder.glob("*.json"), key=delivery_key)
