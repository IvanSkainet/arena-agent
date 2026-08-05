#!/usr/bin/env python3
"""Find security checks that switch themselves off when a value is empty.

Three bugs in two releases had the same shape, and each was fixed on its
own before the pattern was named:

    #51  if expected and got.lower() != expected.lower():   runtimes.py
    #54  if not _TOKEN: return True                         helper_server.py
    #61  if expected_sha256:                                auto_update.py

Every one reads as "verify this", and every one means "verify this, if
somebody remembered to supply the thing to verify against". An optional
check written as a truthiness test is a check that is off by default,
and the default is reached exactly when the caller is sloppiest.

Two shapes are reported.

**gated-refusal** -- a refusal (raise / return an error / send 4xx) sits
inside `if <secret>:` or `if <secret> and <comparison>:`. Empty value,
no refusal, execution continues as though the check had passed.

**absent-means-allowed** -- `if not <secret>: return True` (or any
truthy allow). The absence of a credential is treated as permission.

Both are *shapes*, not verdicts. Plenty of legitimate code looks like
this -- `if token: headers["Authorization"] = ...` skips a header rather
than a check, and `if verify:` gates an optional post-condition. The
whole `arena/` tree was audited by hand when this was written: 20
candidates for the loose form, all 20 legitimate. So the ratchet works
off an explicit allowlist with a reason per entry, and the reason has to
say why an empty value is safe there.

Usage:
    python scripts/failopen_ratchet.py            # check (exit 1 on new)
    python scripts/failopen_ratchet.py --list     # show every candidate
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Identifier fragments that name something a security decision rests on.
SECURITY_WORDS = (
    "sha256", "digest", "checksum", "signature",
    "token", "secret", "consent", "hmac", "credential", "apikey",
    # "expected" on its own matches `expected_output_substr` in browser
    # diagnostics, which gates a heuristic rather than a security check.
    # Pair it with what it is expected to BE.
    "expected_sha", "expected_digest", "expected_hash", "expected_token",
    "expected_signature",
)

# Words that make a `return` a refusal rather than a success.
REFUSAL_WORDS = (
    "_err(", "false", "error", "mismatch", "unauthor", "refus",
    "reject", "denied", "forbidden", "invalid",
)

# Reviewed and legitimate. The reason must explain why an EMPTY value is
# safe -- "it is just an optional header" is a reason; "it looks fine" is
# not. Keys are "<path>:<line>:<shape>" so a line moving forces a re-read.
ALLOWLIST: dict[str, str] = {
    "arena/admin/zerotier_central.py:170:gated-refusal": (
        "Transport failure vs HTTP error, in the ZeroTier Central client. The token is already mandatory a few lines above (`if not token: return _no_token_response()`) and a non-2xx status is refused by the next branch, so this pair only chooses WHICH error to report. Eight call sites share the shape."
    ),
    "arena/admin/zerotier_central.py:196:gated-refusal": (
        "Transport failure vs HTTP error, in the ZeroTier Central client. The token is already mandatory a few lines above (`if not token: return _no_token_response()`) and a non-2xx status is refused by the next branch, so this pair only chooses WHICH error to report. Eight call sites share the shape."
    ),
    "arena/admin/zerotier_central.py:236:gated-refusal": (
        "Transport failure vs HTTP error, in the ZeroTier Central client. The token is already mandatory a few lines above (`if not token: return _no_token_response()`) and a non-2xx status is refused by the next branch, so this pair only chooses WHICH error to report. Eight call sites share the shape."
    ),
    "arena/admin/zerotier_central.py:260:gated-refusal": (
        "Transport failure vs HTTP error, in the ZeroTier Central client. The token is already mandatory a few lines above (`if not token: return _no_token_response()`) and a non-2xx status is refused by the next branch, so this pair only chooses WHICH error to report. Eight call sites share the shape."
    ),
    "arena/admin/zerotier_central.py:283:gated-refusal": (
        "Transport failure vs HTTP error, in the ZeroTier Central client. The token is already mandatory a few lines above (`if not token: return _no_token_response()`) and a non-2xx status is refused by the next branch, so this pair only chooses WHICH error to report. Eight call sites share the shape."
    ),
    "arena/admin/zerotier_central.py:346:gated-refusal": (
        "Transport failure vs HTTP error, in the ZeroTier Central client. The token is already mandatory a few lines above (`if not token: return _no_token_response()`) and a non-2xx status is refused by the next branch, so this pair only chooses WHICH error to report. Eight call sites share the shape."
    ),
    "arena/admin/zerotier_central.py:379:gated-refusal": (
        "`err and status == 0` distinguishes a transport failure from an "
        "HTTP error. The token itself is already required above "
        "(`if not token: return _no_token_response()`), and a non-2xx "
        "status is refused by the next branch either way."
    ),
    "arena/admin/zerotier_central.py:403:gated-refusal": (
        "Same shape, same function family: the token check precedes it and "
        "_ok_status() refuses everything this branch lets through."
    ),
    "arena/auth/users.py:77:gated-refusal": (
        "`if users:` gates the multi-user table, not the auth decision. An "
        "empty table falls through to the single shared config token below "
        "-- which is compared with hmac.compare_digest. No users configured "
        "means 'nobody has a per-user token', not 'everybody is allowed'."
    ),
    "arena/autonomy/yolo.py:68:gated-refusal": (
        "Deliberate and documented in the docstring: enabling YOLO requires "
        "the ack token, DISABLING never does. Failing closed on the disable "
        "path would strand an operator with auto-approve stuck on."
    ),
    "arena/multiagent/handlers_agents.py:37:gated-refusal": (
        "`if is_agent:` adds a restriction rather than granting access -- an "
        "agent token is refused from /v1/agents/*. Master-token auth already "
        "happened upstream via @authed; is_agent False means 'authenticated "
        "as master', not 'unauthenticated'."
    ),
    "arena/system/handlers.py:152:gated-refusal": (
        "Same pattern as handlers_agents.py:37 -- an extra refusal layered "
        "on top of @authed, not the authentication itself."
    ),
}


def _names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id.lower())
        elif isinstance(child, ast.Attribute):
            found.add(child.attr.lower())
    return found


def _mentions_secret(node: ast.AST) -> bool:
    names = _names(node)
    return any(word in name for name in names for word in SECURITY_WORDS)


def _contains_refusal(body: list[ast.stmt]) -> bool:
    module = ast.Module(body=list(body), type_ignores=[])
    for node in ast.walk(module):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Return) and node.value is not None:
            source = ast.unparse(node.value).lower()
            if any(word in source for word in REFUSAL_WORDS):
                return True
        if isinstance(node, ast.Call):
            source = ast.unparse(node).lower()
            if "send_response(4" in source or "send_response(5" in source:
                return True
    return False


def _returns_allow(body: list[ast.stmt]) -> bool:
    """`return True` as the whole body -- an explicit allow.

    A bare `return` is NOT counted. `_apply_authtoken` ends with one and
    means "nothing to configure"; reading that as "access granted" is
    how a detector earns its reputation for crying wolf. An allow has to
    say True.
    """
    statements = [s for s in body if not isinstance(s, ast.Pass)]
    if len(statements) != 1 or not isinstance(statements[0], ast.Return):
        return False
    value = statements[0].value
    return isinstance(value, ast.Constant) and value.value is True


def scan_file(path: pathlib.Path) -> list[tuple[int, str, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []

    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test

        # Shape B first: `if not <secret>: <allow>`
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            if _mentions_secret(test.operand) and _returns_allow(node.body):
                hits.append((node.lineno, "absent-means-allowed",
                             ast.unparse(test)[:70]))
            continue

        # Shape A: a refusal gated behind the secret's own truthiness.
        gate: ast.AST | None = None
        if isinstance(test, (ast.Name, ast.Attribute)):
            gate = test
        elif (isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And)
                and isinstance(test.values[0], (ast.Name, ast.Attribute))
                and any(isinstance(v, ast.Compare) for v in test.values[1:])):
            gate = test.values[0]
        if gate is None:
            continue
        # The gate may be named vaguely -- bug #51 used a bare `expected`.
        # What makes it a security gate is the company it keeps, so judge
        # the whole condition plus the refusal it guards. That catches
        # `if expected and got != expected: raise ...sha256 mismatch...`
        # while leaving `if expected_output_substr and ...` alone, since
        # nothing in the browser-diagnostics branch names a secret.
        context = (ast.unparse(test) + " "
                   + " ".join(ast.unparse(s) for s in node.body)).lower()
        if not any(word in context for word in SECURITY_WORDS):
            continue
        if _contains_refusal(node.body) and not (
                node.orelse and _contains_refusal(node.orelse)):
            hits.append((node.lineno, "gated-refusal", ast.unparse(test)[:70]))
    return hits


def collect() -> list[tuple[str, int, str, str]]:
    out: list[tuple[str, int, str, str]] = []
    for path in sorted((ROOT / "arena").rglob("*.py")):
        # as_posix(), not str(): Windows renders this as
        # `arena\admin\zerotier_central.py`, which matches no allowlist key
        # and turned every reviewed entry back into a "new candidate" on
        # five Windows runners. The keys are written with forward slashes
        # because a review record should read the same everywhere.
        rel = path.relative_to(ROOT).as_posix()
        for lineno, shape, source in scan_file(path):
            out.append((rel, lineno, shape, source))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true",
                        help="print every candidate, allow-listed or not")
    args = parser.parse_args()

    found = collect()
    if args.list:
        for rel, lineno, shape, source in found:
            key = f"{rel}:{lineno}:{shape}"
            mark = "OK " if key in ALLOWLIST else "NEW"
            print(f"{mark} {shape:22} {rel}:{lineno}  {source}")
        return 0

    unknown = [(r, ln, sh, src) for r, ln, sh, src in found
               if f"{r}:{ln}:{sh}" not in ALLOWLIST]
    if unknown:
        print("FAIL-OPEN CANDIDATES (a security check that switches itself "
              "off when its input is empty):\n")
        for rel, lineno, shape, source in unknown:
            print(f"  {shape:22} {rel}:{lineno}")
            print(f"      {source}")
        print("\nEither make the check unconditional -- require the value, or "
              "take an explicit opt-out argument -- or add the entry to "
              "ALLOWLIST in this script with a reason explaining why an "
              "EMPTY value is safe there.")
        return 1

    print(f"OK: no ungated fail-open checks ({len(found)} allow-listed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
