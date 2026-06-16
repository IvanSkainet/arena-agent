"""Memory CLI argument parsing helpers."""
from __future__ import annotations

from arena.memory.cli_paths import *  # noqa: F401,F403

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
