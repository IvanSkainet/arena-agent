"""File-backed message store for the operator <-> agent relay.

One JSON file per message, atomic writes, no database. The bridge already
owns a state directory and the tasks queue proved the shape works; this
is the same idea for prose instead of commands.

Design notes worth keeping:

* **Claiming is atomic.** `claim_next` uses `os.rename`, which is atomic
  on POSIX and on Windows when source and destination share a volume.
  Two agents polling at once therefore cannot both receive the same
  message -- the loser's rename raises and it moves to the next file.
* **Waiting is polling, deliberately.** A 200ms stat loop is unglamorous
  and it works identically on Windows, macOS and Linux, across network
  drives, and with no dependency. inotify/ReadDirectoryChangesW would be
  three implementations and a class of platform bugs this project has
  been bitten by before (bugs #52, #63, #68 were all "worked on the
  author's OS").
* **Nothing here executes anything.** That is the whole point of not
  reusing `arena/tasks`.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Cap a single message. The relay is for instructions and answers, not
# file transfer -- there is /v1/fs for that. An unbounded field here would
# let one message fill the operator's disk.
MAX_BODY_BYTES = 64 * 1024

POLL_INTERVAL_S = 0.2


@dataclass
class RelayMessage:
    id: str
    body: str
    sender: str
    created_at: float
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "body": self.body,
            "sender": self.sender,
            "created_at": self.created_at,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RelayMessage:
        return cls(
            id=str(raw.get("id", "")),
            body=str(raw.get("body", "")),
            sender=str(raw.get("sender", "unknown")),
            created_at=float(raw.get("created_at", 0.0)),
            meta=raw.get("meta") or {},
        )


def _dirs(root: Path) -> tuple[Path, Path, Path]:
    inbox = root / "inbox"
    claimed = root / "claimed"
    replies = root / "replies"
    for d in (inbox, claimed, replies):
        d.mkdir(parents=True, exist_ok=True)
    return inbox, claimed, replies


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON so a reader never sees a half-written file.

    A partially written message would be parsed as corrupt and dropped,
    which on a channel whose whole job is not losing the operator's words
    is not an acceptable failure mode.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def send_message(root: Path, body: str, *, sender: str = "operator",
                 meta: dict[str, Any] | None = None) -> RelayMessage:
    """Queue a message for the agent. Raises ValueError on bad input."""
    if not isinstance(body, str) or not body.strip():
        raise ValueError("message body is required")
    encoded = body.encode("utf-8")
    if len(encoded) > MAX_BODY_BYTES:
        raise ValueError(
            f"message is {len(encoded)} bytes; the relay caps a single "
            f"message at {MAX_BODY_BYTES} (use /v1/fs for files)"
        )
    inbox, _claimed, _replies = _dirs(root)
    msg = RelayMessage(
        id=uuid.uuid4().hex[:12],
        body=body,
        sender=sender,
        created_at=time.time(),
        meta=meta or {},
    )
    # Name files by timestamp so a plain sort is FIFO. The id suffix keeps
    # two messages in the same millisecond from colliding.
    name = f"{msg.created_at:015.4f}-{msg.id}.json"
    _write_atomic(inbox / name, msg.to_dict())
    return msg


def inbox_depth(root: Path) -> int:
    inbox, _c, _r = _dirs(root)
    return len(list(inbox.glob("*.json")))


def list_messages(root: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    inbox, claimed, replies = _dirs(root)
    out: list[dict[str, Any]] = []
    for state, folder in (("inbox", inbox), ("claimed", claimed), ("replies", replies)):
        for path in sorted(folder.glob("*.json"))[:limit]:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                out.append({"id": path.stem, "state": state, "error": "unreadable"})
                continue
            raw["state"] = state
            out.append(raw)
    return out[:limit]


def claim_next(root: Path) -> RelayMessage | None:
    """Take the oldest message exactly once. None when the inbox is empty.

    v4.166.0: this used `os.rename`, and the whole Windows matrix went red
    with `lost -29 message(s)` -- a NEGATIVE count, meaning messages were
    delivered *more* than once. On POSIX `os.rename` silently replaces an
    existing destination and the loser of a race gets FileNotFoundError,
    so the claim held; Windows semantics differ enough that it did not,
    and 16 threads found it in CI while 300 messages across 16 threads on
    Linux never reproduced it locally.

    Rather than reason about which platform guarantees what, the claim now
    rests on something both agree on: `os.open` with `O_CREAT | O_EXCL`
    fails if the file already exists, everywhere. The winner creates a
    lock file named after the message; everyone else moves on. A
    duplicated instruction is worse than a lost one -- "delete the branch"
    run twice is a different outcome than run once -- so this is the one
    property worth paying an extra syscall for.
    """
    inbox, claimed, _replies = _dirs(root)
    for path in sorted(inbox.glob("*.json")):
        lock = claimed / (path.name + ".lock")
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # Another claimer owns this one.
            continue
        except OSError:
            continue
        os.close(fd)

        target = claimed / path.name
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Unreadable: do not jam the queue behind it. Move it aside so
            # it can be inspected, and keep the lock so nobody retries it.
            try:
                os.replace(path, target)
            except OSError:
                pass
            continue
        try:
            # os.replace, not os.rename: defined to overwrite on BOTH
            # platforms, so a leftover file from an earlier crash cannot
            # wedge the queue.
            os.replace(path, target)
        except OSError:
            # The bytes are already in hand and the lock is ours, so the
            # message is still delivered exactly once. Losing the file move
            # costs an inspection copy, not a message.
            pass
        return RelayMessage.from_dict(raw)
    return None


def wait_for_message(root: Path, *, timeout: float = 25.0,
                     now: Any = time.monotonic,
                     sleep: Any = time.sleep) -> RelayMessage | None:
    """Long-poll for the next message.

    `now`/`sleep` are injectable so tests drive the clock instead of
    racing it -- the metrics staleness gate had to be rewritten for
    exactly that reason.
    """
    deadline = now() + max(0.0, timeout)
    while True:
        msg = claim_next(root)
        if msg is not None:
            return msg
        if now() >= deadline:
            return None
        sleep(POLL_INTERVAL_S)


def post_reply(root: Path, in_reply_to: str, body: str, *,
               sender: str = "agent") -> RelayMessage:
    """Answer a message. The operator picks this up with `read_replies`."""
    if not isinstance(in_reply_to, str) or not in_reply_to.strip():
        raise ValueError("in_reply_to is required")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("reply body is required")
    encoded = body.encode("utf-8")
    if len(encoded) > MAX_BODY_BYTES:
        raise ValueError(f"reply is {len(encoded)} bytes; cap is {MAX_BODY_BYTES}")
    _inbox, _claimed, replies = _dirs(root)
    msg = RelayMessage(
        id=uuid.uuid4().hex[:12],
        body=body,
        sender=sender,
        created_at=time.time(),
        meta={"in_reply_to": in_reply_to},
    )
    name = f"{msg.created_at:015.4f}-{msg.id}.json"
    _write_atomic(replies / name, msg.to_dict())
    return msg


def read_replies(root: Path, *, in_reply_to: str = "",
                 consume: bool = True) -> list[RelayMessage]:
    """Collect replies, optionally filtered to one conversation."""
    _inbox, _claimed, replies = _dirs(root)
    found: list[RelayMessage] = []
    for path in sorted(replies.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if in_reply_to and (raw.get("meta") or {}).get("in_reply_to") != in_reply_to:
            continue
        found.append(RelayMessage.from_dict(raw))
        if consume:
            path.unlink(missing_ok=True)
    return found


def prune(root: Path, *, older_than_seconds: float = 7 * 86400,
          keep_recent: int = 200) -> dict[str, int]:
    """Delete claimed messages the operator will never look at again.

    v4.166.0: nothing removed anything. Measured before adding this --
    500 messages read and answered left **1000 files** in `claimed/`
    (the message plus its lock), growing forever. Small in bytes, but an
    unbounded file count is the kind of thing that is fine for a month
    and then makes `glob` slow and a backup noisy.

    Only `claimed/` is pruned. `inbox/` holds messages nobody has read,
    and deleting those on a timer would silently discard the operator's
    words -- exactly the failure this whole channel exists to avoid.
    `replies/` is consumed on read, so it empties itself.

    Two conditions, both must hold: older than the age limit AND outside
    the newest `keep_recent`. The count floor means a burst of traffic
    cannot age everything out at once and leave nothing to inspect after
    an incident.
    """
    _inbox, claimed, _replies = _dirs(root)
    entries = sorted(claimed.glob("*"), key=lambda p: p.name)
    cutoff = time.time() - max(0.0, older_than_seconds)
    protected = {p.name for p in entries[-keep_recent:]} if keep_recent > 0 else set()

    removed = 0
    for path in entries:
        if path.name in protected:
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError:
            # A file that cannot be removed is not worth failing a
            # housekeeping pass over; it will be retried next time.
            continue
    return {"removed": removed, "remaining": len(entries) - removed}


def wait_for_reply(root: Path, in_reply_to: str, *, timeout: float = 300.0,
                   now: Any = time.monotonic,
                   sleep: Any = time.sleep) -> RelayMessage | None:
    deadline = now() + max(0.0, timeout)
    while True:
        found = read_replies(root, in_reply_to=in_reply_to, consume=True)
        if found:
            return found[0]
        if now() >= deadline:
            return None
        sleep(POLL_INTERVAL_S)
