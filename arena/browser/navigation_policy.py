"""Navigation policy for agent-facing browser surfaces.

`browser.read` has always refused to fetch a private address: `browser_read`
takes `validate_url` as a *required* keyword and calls it before the request.
The CDP navigation path grew without that decision applied to it, so
`Page.navigate` accepted `file://`, loopback and link-local targets that the
same bridge rejects one endpoint over. This module carries the missing half of
that decision, in one place, so every agent-facing entry point asks the same
question.

Three things are deliberate here.

**The policy is separate from its application.** `navigation_error` is a pure
function of a URL string and an environment mapping; the handlers translate
its verdict into an HTTP response. That split is what makes the policy
testable without a browser, and it mirrors `arena/exec/control_gate.py`,
which was extracted for the same reason after #93.

**It is not the SSRF validator, and it does not pretend to be.**
`security_ssrf._validate_url` resolves the host and answers "is this public?".
Chromium then resolves the host *again*, on its own, and connects to whatever
it gets. Nothing in this process pins the address the validator approved, so a
DNS entry that changes between the two lookups is navigated to unchecked. That
is the rebinding TOCTOU which T62 closed for urllib by pinning the resolved IP
into the connection (`arena.security_http.open_public_url`); the same trick is
not available through CDP, because the socket belongs to the browser.

So the guarantee offered here is deliberately narrower and stated plainly:
this rejects targets that are *statically* private, and it rejects the schemes
that make a navigation something other than a web fetch. A hostname that
resolves to a private address at navigation time is caught only when the
lookup happens to agree with ours. Claiming more would be the "green means it
works" failure the project keeps writing tests against -- see
`docs/SECURITY.md`, "CDP navigation" for the operator-facing wording.

**Local navigation stays possible, but only on purpose.** Driving a browser
against `http://localhost:3000` is the normal way to test a local app, and a
bridge that made that impossible would simply be routed around. Setting
`ARENA_BROWSER_ALLOW_LOCAL_NAVIGATION=1` restores the old behaviour for
private and loopback destinations. It does *not* re-enable `file://` or the
other non-web schemes: reading local files is not "local development", and the
opt-in is not a way to ask for it.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from arena.security_ssrf import (
    _BLOCKED_HOSTNAMES,
    _coerce_ip,
    _ip_is_blocked,
    _looks_numeric_host,
)

#: Env var that re-permits private/loopback navigation targets.
LOCAL_NAVIGATION_ENV = "ARENA_BROWSER_ALLOW_LOCAL_NAVIGATION"

#: Truthy spellings accepted for the opt-in, matching `scenarios/storage.py`.
_TRUTHY = frozenset({"1", "true", "yes"})

#: C0 control characters. Chromium strips these from a URL before parsing it;
#: `urlparse` keeps them, so a URL containing one means different things to
#: the validator and to the browser.
_C0_CONTROLS = frozenset(chr(code) for code in range(0x20))

#: DNS runs on its own small pool rather than the loop's default executor.
#: `getaddrinfo` cannot be interrupted, so a lookup abandoned at the timeout
#: keeps its thread until the resolver finally answers. On the default
#: executor those abandoned threads accumulate against the same pool every
#: other `run_in_executor` caller shares -- admin handlers, funnel status,
#: browser fetch -- and a stream of slow hostnames would starve them. They
#: also block `loop.shutdown_default_executor()`, so a clean shutdown would
#: wait on a resolver nobody is listening to any more. Bounded here instead:
#: the damage of a hostile resolver stops at this pool, and a caller that
#: cannot get a worker times out and is treated as unresolved, which is the
#: existing failure mode rather than a new one.
_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nav-dns")

#: Seconds an async caller waits for the policy's DNS lookup before giving up
#: on it. Deliberately short: the lookup is a best-effort extra check, not the
#: load-bearing one, and a navigation request should not sit behind a slow
#: resolver. Exceeding it is treated as "not proven private", the same as a
#: resolver failure.
DNS_TIMEOUT_SECONDS = 2.0

#: Schemes a navigation may use. `Page.navigate` accepts far more than this --
#: `file:`, `data:`, `javascript:`, `chrome:`, `devtools:`, `view-source:` --
#: and each turns "navigate" into something other than fetching a web page.
#: An allowlist rather than a blocklist: the set of URL schemes Chromium
#: understands is neither short nor fixed, so enumerating the bad ones is a
#: losing game.
ALLOWED_SCHEMES = ("http", "https")

#: Navigating a *new* tab to a blank page is how tabs are opened; the string
#: never leaves the process and reaches no network. Allowed as an exact match
#: only -- `about:` in general is not (`about:cache`, `about:net-internals`).
BLANK_URL = "about:blank"

#: Error strings. Exposed as constants because the tests assert on them and
#: the dashboard matches them; retyping the text in three places is how the
#: wording drifts.
ERROR_EMPTY = "missing 'url' parameter"
ERROR_INVALID = "invalid URL"
ERROR_SCHEME = (
    "URL scheme {scheme!r} not allowed for navigation (only http/https)"
)
ERROR_NO_HOST = "missing host"
ERROR_ENCODED_HOST = "percent-encoded host not allowed for navigation"
ERROR_CREDENTIALS = "embedded credentials not allowed for navigation"
ERROR_INTERNAL_HOST = "internal/metadata hostname not allowed"
ERROR_PRIVATE = (
    "private/internal address not allowed for navigation "
    f"(set {LOCAL_NAVIGATION_ENV}=1 to permit local targets)"
)
ERROR_MALFORMED_NUMERIC = "malformed numeric address not allowed"
ERROR_RESOLVED_PRIVATE = (
    "host resolves to a private/internal address "
    f"(set {LOCAL_NAVIGATION_ENV}=1 to permit local targets)"
)


class NavigationRejected(ValueError):
    """A navigation target failed the policy.

    A `ValueError` rather than a bespoke base: the CDP call sites already
    funnel exceptions into 500-with-message responses, and the handlers that
    care translate this one into a 400 explicitly. Subclassing something they
    do not catch would turn a rejected URL into an unhandled traceback.
    """


def local_navigation_allowed(env: Mapping[str, str] | None = None) -> bool:
    """True when the operator opted into private/loopback navigation."""
    source = os.environ if env is None else env
    return source.get(LOCAL_NAVIGATION_ENV, "").strip().lower() in _TRUTHY


def _resolves_to_blocked(host: str) -> bool:
    """Best-effort DNS check: does *host* currently answer with a private IP?

    Names like `localtest.me` resolve to 127.0.0.1 while looking perfectly
    public as a string, so skipping this would leave the most convenient
    spelling of "navigate to my loopback" wide open.

    Best-effort is the honest description, for two reasons. Chromium resolves
    the name again when it navigates, so a record that changes in between is
    not covered (see the module docstring on the T62 pinning that CDP cannot
    reuse). And a resolver failure is treated as "not proven private" rather
    than as a rejection: an offline host would otherwise be unable to navigate
    anywhere at all, which turns a security check into an outage.
    """
    try:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    for *_unused, sockaddr in answers:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _ip_is_blocked(address):
            return True
    return False


def _static_navigation_error(
    url: object,
    *,
    env: Mapping[str, str] | None = None,
    allow_blank: bool = True,
) -> tuple[str | None, str | None]:
    """Every check that needs no resolver, plus the host still to be resolved.

    Split out of `navigation_error` so the two callers can share it: the
    synchronous entry points resolve inline, the async ones hand the host to a
    thread. Both therefore apply an identical set of string-level rules --
    which is the point of having one policy module -- and only the DNS step
    differs. Returns `(error, host_to_resolve)`; `host_to_resolve` is None when
    the verdict is already settled and no lookup is needed.
    """
    if not isinstance(url, str) or not url.strip():
        return ERROR_EMPTY, None

    candidate = url.strip()
    if allow_blank and candidate.lower() == BLANK_URL:
        return None, None

    # Chromium follows the WHATWG URL Standard, which treats a backslash in
    # the authority as a path separator; Python's `urlparse` follows RFC 3986,
    # which does not. The two therefore disagree about where the host ends:
    #
    #   http://127.0.0.1\@evil.com/
    #     urlparse -> host "evil.com"   (public, allowed)
    #     Chromium -> host "127.0.0.1"  (the backslash ends the authority)
    #
    # Validating one host and navigating to another is the whole defect this
    # module exists to close, so a URL the two parsers may read differently is
    # refused outright rather than approved on Python's reading. Same reasoning
    # as `security_ssrf._components_fit_ipv4`, which refuses libc-dependent
    # numeric spellings instead of guessing which library wins.
    if "\\" in candidate:
        return ERROR_INVALID, None

    # Raw whitespace and control characters are stripped by Chromium before
    # parsing and preserved by `urlparse`, producing the same disagreement:
    # `http://ex\tample.com/` is `example.com` to one and `ex\tample.com` --
    # a name that resolves nowhere -- to the other.
    # `isspace()` already covers space/tab/newline/CR and the Unicode spaces;
    # the second clause catches the remaining C0 controls (NUL, BEL, ESC...),
    # which are not "space" but are stripped by Chromium just the same.
    if any(character.isspace() or character in _C0_CONTROLS for character in candidate):
        return ERROR_INVALID, None

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ERROR_INVALID, None

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return ERROR_SCHEME.format(scheme=parsed.scheme), None

    try:
        host = (parsed.hostname or "").strip().rstrip(".").lower()
    except ValueError:
        # urlparse defers IPv6 bracket errors to `.hostname`.
        return ERROR_INVALID, None
    if not host:
        return ERROR_NO_HOST, None

    # A third parser differential, and the one the backslash fix missed.
    # Chromium percent-decodes the host of a special (http/https) URL before
    # it parses it; `urlparse` hands back the escaped bytes verbatim:
    #
    #   http://localho%73t/                 -> urlparse "localho%73t"  (a name
    #     that resolves nowhere, so allowed) / Chromium "localhost"
    #   http://%31%32%37%2e%30%2e%30%2e%31/ -> urlparse "%31%32..."     (not
    #     numeric to us, so no IP check) / Chromium 127.0.0.1
    #
    # Decoding it here and re-checking would mean reimplementing Chromium's
    # host canonicalisation and staying bug-compatible with it forever. A
    # legitimate http(s) host has no reason to be escaped -- non-ASCII names
    # travel as IDNA punycode, not percent-escapes -- so the escape itself is
    # refused. Only the host is affected; path and query keep their encoding.
    if "%" in host:
        return ERROR_ENCODED_HOST, None

    # `security_http.open_public_url` already refuses these for the urllib
    # transport; a URL the bridge will not fetch should not be one it will
    # navigate to. Credentials in a navigation target are also the classic way
    # to make the authority hard to read at a glance
    # (`https://trusted.example.com@evil.test/`), and Chromium hands them to
    # the origin as a Basic auth header.
    if parsed.username is not None or parsed.password is not None:
        return ERROR_CREDENTIALS, None

    # Checked *after* the parser-differential and credential rejections and
    # before the address checks: the opt-in exists to permit private
    # destinations, not to switch the policy off. A URL two parsers read
    # differently is not a "local target", it is a malformed one.
    if local_navigation_allowed(env):
        return None, None

    if (
        host in _BLOCKED_HOSTNAMES
        or host.endswith(".localhost")
        or host.endswith(".localdomain")
        or host.endswith(".internal")
        or host.endswith(".local")
    ):
        return ERROR_INTERNAL_HOST, None

    address = _coerce_ip(host)
    if address is not None and _ip_is_blocked(address):
        return ERROR_PRIVATE, None
    if address is None and _looks_numeric_host(host):
        # An all-numeric host the coercer refused is an out-of-range address
        # spelling, not a name. Letting it through would defer the verdict to
        # whatever libc Chromium is linked against -- the parser differential
        # `security_ssrf` documents at length.
        return ERROR_MALFORMED_NUMERIC, None

    if address is not None:
        # A literal address was checked above and found acceptable; there is
        # nothing left for a resolver to say about it.
        return None, None

    return None, host


def navigation_error(
    url: object,
    *,
    env: Mapping[str, str] | None = None,
    allow_blank: bool = True,
) -> str | None:
    """Return why *url* may not be navigated to, or None when it is allowed.

    `allow_blank` covers the tab-opening path, where ``about:blank`` is the
    default value rather than a destination anyone asked for.

    Synchronous, and therefore for synchronous callers -- the MCP dispatchers,
    which are plain functions. Inside a coroutine use `navigation_error_async`:
    the lookup this may perform is a blocking `getaddrinfo`, and the bridge
    multiplexes every service through one event loop.
    """
    error, host = _static_navigation_error(url, env=env, allow_blank=allow_blank)
    if error is not None or host is None:
        return error
    if _resolves_to_blocked(host):
        return ERROR_RESOLVED_PRIVATE
    return None


async def navigation_error_async(
    url: object,
    *,
    env: Mapping[str, str] | None = None,
    allow_blank: bool = True,
    dns_timeout: float = DNS_TIMEOUT_SECONDS,
) -> str | None:
    """`navigation_error` for coroutines: the DNS lookup cannot stall the loop.

    Every string-level rule is decided inline -- they are pure string work and
    moving them to a thread would only add latency. Only the resolver call is
    offloaded, and it is bounded:

    * `socket.getaddrinfo` is synchronous with no application-level timeout,
      so calling it from a handler lets an attacker-chosen hostname served by
      a deliberately slow resolver stall the shared aiohttp loop, and with it
      the gateway, SSE, WebSocket, dashboard and task-runner traffic that has
      nothing to do with browsing.
    * A lookup that outruns `dns_timeout` is treated the way a resolver
      failure already is -- "not proven private", not "rejected". A timeout
      that blocked navigation would hand anyone able to slow the resolver an
      outage; consistency with the existing failure mode is also what keeps
      this check honestly labelled best-effort.

    The thread keeps running after a timeout -- `getaddrinfo` is not
    interruptible -- but it belongs to this module's own small pool
    (`_DNS_EXECUTOR`), so an abandoned lookup cannot starve the executor the
    rest of the process shares, nor delay its shutdown.
    """
    error, host = _static_navigation_error(url, env=env, allow_blank=allow_blank)
    if error is not None or host is None:
        return error

    loop = asyncio.get_running_loop()
    try:
        blocked = await asyncio.wait_for(
            loop.run_in_executor(_DNS_EXECUTOR, _resolves_to_blocked, host),
            timeout=dns_timeout,
        )
    except (asyncio.TimeoutError, RuntimeError):
        # RuntimeError: the pool is shutting down, which is not a verdict
        # about the URL either.
        return None
    return ERROR_RESOLVED_PRIVATE if blocked else None
