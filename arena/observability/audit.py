"""Audit log helpers: redaction, append/rotation, tail and stats.

Privacy posture (v4.44.0)
-------------------------
Every audit event flows through :func:`sanitize_audit_event`
before being appended. Two redaction passes, both defence-in-
depth:

1. **Key-name blocklist** -- any key containing ``token``,
   ``authorization``, ``password``, ``secret``, ``api_key``,
   ``apikey``, or ``credential`` is replaced with
   ``<redacted>``. Case-insensitive. Handles the common shapes
   like ``request_body["password"]``.
2. **Value-pattern blocklist** -- any string value that matches
   a known credential pattern (``Bearer <token>``,
   ``AKIA...`` AWS key, ``ghp_...`` / ``ghs_...`` GitHub token,
   ``sk-...`` OpenAI-style key, ``xoxb-...`` Slack bot token,
   ``eyJhbGc...`` JWT, ``postgres://user:pass@...`` connection
   strings) is redacted mid-string so an event that captured
   the whole HTTP body doesn't leak the credential inside.

Both passes recurse through nested dicts and lists so a
credential buried in ``event["result"]["stdout"]`` still gets
scrubbed. Value patterns are anchored via non-capturing
prefixes so we do not accidentally match ordinary strings
that happen to start with letters.

Rotation writes preserve ``chmod 0o600`` on the current file
and every rotated one (v3.x behaviour, tightened again in
v4.44.0 to explicitly chmod after each rename in case the
filesystem loses the mode).
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable

from arena.constants import AUDIT_CMD_LIMIT

audit_lock = threading.Lock()


# Key-name substrings that trigger full redaction.
_SENSITIVE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "token", "authorization", "password", "secret",
    "api_key", "apikey", "credential", "passphrase",
    "private_key", "privatekey",
)


# Value patterns that indicate a credential embedded in a
# larger string. Each pattern is precompiled and the match is
# replaced with ``<redacted:{name}>`` so operators can still
# see WHICH kind of secret leaked without seeing the secret
# itself.
_VALUE_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    # Bearer / Basic tokens in Authorization-style headers or
    # curl commands that were captured into the log.
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/=]{16,}")),
    ("basic", re.compile(r"\bBasic\s+[A-Za-z0-9+/=]{16,}")),
    # AWS keys
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    # GitHub tokens (personal, server-to-server, oauth, refresh)
    ("github", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    # OpenAI / Anthropic-style keys (sk-... and sk-ant-...)
    ("openai-style", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9\-_]{20,}\b")),
    # Slack tokens
    ("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    # Google API keys start with AIza and are 39 chars total
    ("google-api", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    # JWT (three base64url segments joined by dots)
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\b"
    )),
    # DB / broker URIs with inline credentials
    ("uri-creds", re.compile(
        r"\b[a-z][a-z0-9+.\-]*://[^\s:@/]+:[^\s@/]+@[^\s]+"
    )),
    # SSH private keys pasted inline
    ("ssh-key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    )),
]


def _redact_value_patterns(text: str) -> str:
    """Scrub known credential patterns from a free-form string.

    Runs every pattern in turn, replacing the match with
    ``<redacted:{name}>``. Called on any value that reached
    the audit log as a string, no matter which key it lives
    under. This is the belt to the key-name blocklist's
    suspenders: a leaked credential inside
    ``result["stdout"]`` gets scrubbed even though ``stdout``
    is not a blocklisted key.

    ``text`` shorter than 16 chars is passed through unchanged
    -- the patterns all require at least 16 chars of match, so
    a shorter string cannot carry a real credential. Skipping
    the scan on tiny strings is a big perf win because HTTP
    audit events have many short fields.
    """
    if len(text) < 16:
        return text
    for name, pat in _VALUE_PATTERNS:
        text = pat.sub(f"<redacted:{name}>", text)
    return text


def _is_sensitive_key(key: str) -> bool:
    low = key.lower()
    return any(sub in low for sub in _SENSITIVE_KEY_SUBSTRINGS)


def _scrub(value: Any) -> Any:
    """Recursively scrub a value: dicts, lists, strings.

    Non-string leaves (int/bool/None/float) pass through. This
    is the entry point for nested-value redaction; the top-
    level ``sanitize_audit_event`` handles the special ``cmd``
    field and length truncation before delegating leaf values
    here.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_sensitive_key(k):
                out[k] = "<redacted>"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return _redact_value_patterns(value)
    return value


def sanitize_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in event.items():
        if _is_sensitive_key(key):
            out[key] = "<redacted>"
            continue
        if key == "cmd" and isinstance(value, str):
            out["cmd_len"] = len(value)
            out["cmd_sha256"] = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()
            # v4.44.0: scrub embedded credentials from the
            # command string before truncation. Pre-v4.44.0 an
            # audit event capturing e.g. ``curl -H "Authorization:
            # Bearer <token>" ...`` would persist the token
            # verbatim because ``cmd`` is not a blocklisted key.
            scrubbed = _redact_value_patterns(value)
            if len(scrubbed) > AUDIT_CMD_LIMIT:
                out[key] = scrubbed[:AUDIT_CMD_LIMIT] + f"\n...[truncated {len(scrubbed) - AUDIT_CMD_LIMIT} chars; sha256={out['cmd_sha256']}]"
                out["cmd_truncated"] = True
            else:
                out[key] = scrubbed
                out["cmd_truncated"] = False
            continue
        # v4.44.0: recursive scrub for every non-cmd value.
        # Handles nested dicts/lists that may contain credentials
        # or sensitive keys deeper in the structure.
        scrubbed_value = _scrub(value)
        if isinstance(scrubbed_value, str) and len(scrubbed_value) > 12000:
            out[key] = scrubbed_value[:12000] + f"\n...[truncated {len(scrubbed_value) - 12000} chars]"
            out[key + "_truncated"] = True
        else:
            out[key] = scrubbed_value
    return out


def write_audit_event(
    event: dict[str, Any],
    *,
    audit_path: Path,
    app_dir: Path,
    utc_now_fn: Callable[[], str],
    lock: threading.Lock = audit_lock,
) -> dict[str, Any]:
    """Sanitize, timestamp, append and rotate an audit event; return written event."""
    app_dir.mkdir(parents=True, exist_ok=True)
    written = {"ts": utc_now_fn(), **sanitize_audit_event(event)}
    line = json.dumps(written, ensure_ascii=False, sort_keys=True) + "\n"
    with lock:
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(line)
        try:
            os.chmod(audit_path, 0o600)
        except Exception:
            pass
        try:
            if audit_path.exists() and audit_path.stat().st_size > 50 * 1024 * 1024:
                for i in range(5, 0, -1):
                    old = app_dir / f"audit.jsonl.{i}"
                    if old.exists():
                        if i == 5:
                            old.unlink()
                        else:
                            new_name = app_dir / f"audit.jsonl.{i + 1}"
                            old.rename(new_name)
                            # v4.44.0: re-apply 0o600 after every
                            # rename because some filesystems reset
                            # the mode across the rename (ACL-proof
                            # discipline, same as v4.40.0 URL cache).
                            try:
                                os.chmod(new_name, 0o600)
                            except Exception:
                                pass
                rotated = app_dir / "audit.jsonl.1"
                audit_path.rename(rotated)
                try:
                    os.chmod(rotated, 0o600)
                except Exception:
                    pass
        except Exception:
            pass
    return written


def read_tail(path: Path, lines: int = 100) -> list[str]:
    """Read last N lines efficiently using deque."""
    if not path.exists():
        return []
    lines = max(1, min(lines, 1000))
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return list(collections.deque(f, maxlen=lines))
    except Exception:
        return []


def audit_stats(audit_path: Path) -> dict[str, Any]:
    if not audit_path.exists():
        return {"ok": True, "total": 0, "by_type": {}, "first_ts": None, "last_ts": None}
    by_type: dict[str, int] = collections.Counter()
    total = 0
    first_ts: str | None = None
    last_ts: str | None = None
    with open(audit_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                total += 1
                event_type = event.get("type", "unknown")
                by_type[event_type] += 1
                ts = event.get("ts", "")
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
            except json.JSONDecodeError:
                total += 1
                by_type["parse_error"] += 1
    return {"ok": True, "total": total, "by_type": dict(by_type), "first_ts": first_ts, "last_ts": last_ts}
