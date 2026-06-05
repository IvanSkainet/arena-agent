#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
MEM = ROOT / "memory"
FACTS = MEM / "facts.jsonl"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def append(obj: dict) -> None:
    MEM.mkdir(parents=True, exist_ok=True)
    with FACTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        os.chmod(FACTS, 0o600)
    except Exception:
        pass


def _expand_tags(tokens: list[str]) -> list[str]:
    tags: list[str] = []
    for token in tokens:
        for part in str(token).split(","):
            tag = part.strip()
            if tag:
                tags.append(tag)
    return tags


def _split_remember_rest(rest: list[str]) -> tuple[list[str], list[str]]:
    """Parse flexible remember syntax.

    Supported forms:
      memory-remember KEY value words --tags tag1 tag2
      memory-remember KEY value words --tags=tag1,tag2
      memory-remember KEY --tags tag1 tag2 -- value words
      memory-remember KEY value words

    The old argparse REMAINDER parser swallowed --tags into value.  We parse the
    tail manually so --tags works predictably and remains backwards-compatible
    for calls that do not use tags.
    """
    rest = list(rest or [])
    tag_idx = None
    tag_inline: str | None = None
    for i, token in enumerate(rest):
        if token == "--tags":
            tag_idx = i
            break
        if token.startswith("--tags="):
            tag_idx = i
            tag_inline = token.split("=", 1)[1]
            break

    if tag_idx is None:
        return rest, []

    before = rest[:tag_idx]
    after = rest[tag_idx + 1 :]
    if tag_inline is not None:
        after = [tag_inline] + after

    # Preferred form: value first, tags last.
    if before:
        return before, _expand_tags(after)

    # Alternate form: tags first, explicit -- separator, then value.
    if "--" in after:
        sep = after.index("--")
        return after[sep + 1 :], _expand_tags(after[:sep])

    raise ValueError(
        "when --tags is placed before value, separate tags and value with '--'; "
        "example: memory-remember key --tags todo recovery -- value words"
    )


def remember(args: argparse.Namespace) -> int:
    value_tokens, tags = _split_remember_rest(args.rest)
    if not value_tokens:
        raise ValueError("value is required")
    append({"ts": now(), "type": "fact", "key": args.key,
            "value": " ".join(value_tokens), "tags": tags})
    print(f"remembered: {args.key} [{','.join(tags) or '-'}]")
    return 0


def recall(args: argparse.Namespace) -> int:
    if not FACTS.exists():
        print("no facts")
        return 0
    q = (args.query or "").lower()
    rows: list[dict] = []
    for line in FACTS.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        hay = (
            str(obj.get("key", "")) + " " +
            str(obj.get("value", "")) + " " +
            json.dumps(obj.get("tags", []), ensure_ascii=False)
        ).lower()
        if q and q not in hay:
            continue
        rows.append(obj)
    for obj in rows[-args.limit:]:
        tags = obj.get("tags") or []
        suffix = f" --tags {','.join(tags)}" if tags else ""
        print(f"[{obj.get('ts')}] {obj.get('key')}: {obj.get('value')}{suffix}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("remember")
    s.add_argument("key")
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s.set_defaults(func=remember)

    s = sub.add_parser("recall")
    s.add_argument("query", nargs="?")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=recall)

    args = p.parse_args()
    try:
        return int(args.func(args) or 0)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
