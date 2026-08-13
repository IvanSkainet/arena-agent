"""Interactive terminal ingress for the generic operator/agent relay.

Some local programs can notify a CLI only by pasting text into its terminal.
That is exactly what Book of Eternity's GM daemon does, but the transport is
not game-specific: a watcher, build harness, debugger, or any other local
program may have the same constraint.

``arena-relay terminal`` looks like a persistent CLI to such a program:

* a normal line is one message;
* a bracketed paste is one message even when it contains many lines;
* the message is queued through the existing authenticated relay mailbox;
* the terminal stays busy until the active agent posts a correlated reply;
* it then returns to an idle prompt and can accept the next dispatch.

This does not start or automate an Arena session.  An already-running agent
must poll the relay, exactly as with the Dashboard and ``arena-relay send``.
"""
from __future__ import annotations

import codecs
import contextlib
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, TextIO

BRACKETED_PASTE_START = "\x1b[200~"
BRACKETED_PASTE_END = "\x1b[201~"
MAX_PROMPT_CHARS = 256 * 1024

# Windows Console line input truncates a long ConPTY paste (510 characters on
# the live Windows 10 host).  Raw VT input preserves the explicit bracketed-
# paste framing sent by the host instead of turning one daemon prompt into a
# short line.  Keep processed input enabled so Ctrl+C still works.
_ENABLE_LINE_INPUT = 0x0002
_ENABLE_ECHO_INPUT = 0x0004
_ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
_STD_INPUT_HANDLE = -10


def windows_raw_input_mode(mode: int) -> int:
    """Return a console mode that preserves long bracketed-paste input."""
    return (mode & ~(_ENABLE_LINE_INPUT | _ENABLE_ECHO_INPUT)) | _ENABLE_VIRTUAL_TERMINAL_INPUT


@contextlib.contextmanager
def raw_terminal_input() -> Iterator[bool]:
    """Temporarily enable raw VT input for a Windows console.

    Yields ``True`` only when the mode change succeeded.  Non-Windows systems
    and redirected stdin keep their original behavior.  Restoration is in a
    ``finally`` block because leaving the operator's console in raw mode after
    Ctrl+C would be a much worse failure than rejecting one dispatch.
    """
    if os.name != "nt":
        yield False
        return

    try:
        import ctypes
        from ctypes import wintypes

        # WinDLL is Windows-only and absent from ctypes' non-Windows type
        # surface even though this branch cannot run there. Resolve it lazily
        # so cross-platform static analysis does not invent a runtime import.
        win_dll = getattr(ctypes, "WinDLL")
        kernel32 = win_dll("kernel32", use_last_error=True)
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetConsoleMode.restype = wintypes.BOOL
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetConsoleMode.restype = wintypes.BOOL

        handle = kernel32.GetStdHandle(wintypes.DWORD(_STD_INPUT_HANDLE & 0xFFFFFFFF))
        invalid_handle = ctypes.c_void_p(-1).value
        original = wintypes.DWORD()
        if handle in (None, 0, invalid_handle) or not kernel32.GetConsoleMode(handle, ctypes.byref(original)):
            yield False
            return
        changed = windows_raw_input_mode(int(original.value))
        if not kernel32.SetConsoleMode(handle, wintypes.DWORD(changed)):
            yield False
            return
    except Exception:
        yield False
        return

    try:
        yield True
    finally:
        try:
            kernel32.SetConsoleMode(handle, original)
        except Exception:
            pass


class PromptTooLargeError(ValueError):
    """Raised before an unbounded terminal paste can consume memory."""


@dataclass
class BufferedTextChunkReader:
    """One non-greedy binary read decoded with the stream's text encoding.

    ``TextIOWrapper.read(4096)`` may wait to fill its requested size.  ``read1``
    performs one underlying read and returns what ConPTY already supplied,
    which both avoids 34,000 per-character Win32 calls and does not wait for a
    future dispatch to fill the final short chunk.
    """

    stream: TextIO
    chunk_size: int = 4096
    _decoder: Any = field(init=False)
    _finalized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        encoding = getattr(self.stream, "encoding", None) or "utf-8"
        self._decoder = codecs.getincrementaldecoder(encoding)(errors="replace")

    def read_chunk(self) -> str:
        binary = getattr(self.stream, "buffer", None)
        read1 = getattr(binary, "read1", None)
        if not callable(read1):
            return self.stream.read(1)
        while True:
            data = read1(self.chunk_size)
            if data:
                decoded = self._decoder.decode(data, final=False)
                # A UTF-8 sequence may straddle two console reads.  Empty here
                # means "need continuation bytes", not EOF.
                if decoded:
                    return decoded
                continue
            if self._finalized:
                return ""
            self._finalized = True
            return self._decoder.decode(b"", final=True)


@dataclass
class PromptStreamReader:
    """Read line or bracketed-paste messages from an interactive stream.

    The closing bracketed-paste marker is not enough to complete a dispatch:
    ConPTY-style hosts paste first, verify that the text became visible, and
    only then send Enter.  Waiting for that final CR/LF keeps the relay's
    ``Working`` marker causally after submission instead of making the host
    believe Enter failed.
    """

    stream: TextIO
    max_chars: int = MAX_PROMPT_CHARS
    on_bracketed_paste: Callable[[str], None] | None = None
    on_input_char: Callable[[str], None] | None = None
    read_chunk: Callable[[], str] | None = None
    submit_gap_seconds: float = 0.05
    now: Callable[[], float] = time.monotonic
    _input_chunk: str = field(default="", init=False)
    _input_index: int = field(default=0, init=False)
    _chunk_wait_seconds: float = field(default=0.0, init=False)
    _chunk_is_newline_only: bool = field(default=False, init=False)

    def _read_char(self) -> str:
        if self._input_index >= len(self._input_chunk):
            started = self.now()
            self._input_chunk = (
                self.read_chunk() if self.read_chunk is not None else self.stream.read(1)
            )
            self._chunk_wait_seconds = max(0.0, self.now() - started)
            self._chunk_is_newline_only = self._input_chunk in {"\r", "\n", "\r\n"}
            self._input_index = 0
            if not self._input_chunk:
                return ""
        char = self._input_chunk[self._input_index]
        self._input_index += 1
        return char

    def _checked_append(
        self,
        chars: list[str],
        char: str,
        *,
        closing_marker: str | None = None,
    ) -> None:
        chars.append(char)
        if len(chars) <= self.max_chars:
            return
        # A bracketed payload may temporarily exceed the content limit only
        # by the bytes of its closing marker, which are removed immediately.
        excess = len(chars) - self.max_chars
        suffix = "".join(chars[-excess:])
        if closing_marker is not None and closing_marker.startswith(suffix):
            return
        raise PromptTooLargeError(
            f"terminal prompt exceeds {self.max_chars} characters"
        )

    def read_prompt(self) -> str | None:
        """Return the next submitted prompt, or ``None`` on EOF."""
        prefix: list[str] = []
        payload: list[str] = []
        bracketed = False
        bracket_closed = False
        conpty_dispatch = False

        while True:
            char = self._read_char()
            if char and self.on_input_char is not None:
                self.on_input_char(char)
            if char == "":
                # Deliver a final ordinary line at EOF, but never a truncated
                # bracketed paste: partial instructions are worse than none.
                if not bracketed and not conpty_dispatch and prefix:
                    text = "".join(prefix).strip().lstrip("\x00\x15")
                    return text or None
                return None

            if not bracketed and not prefix and char == "\x15":
                # BookOfEternityGMBridge's clear-input control is also a
                # framing start when Windows Console strips ESC[200~ / ESC[201~.
                conpty_dispatch = True
                continue

            if bracketed:
                if bracket_closed:
                    if char in "\r\n":
                        text = "".join(payload).strip()
                        return text or ""
                    # Some terminals place harmless NULs between the paste
                    # marker and Enter.  Anything else still belongs to the
                    # submitted payload rather than being silently discarded.
                    if char != "\x00":
                        self._checked_append(payload, char)
                    continue

                self._checked_append(
                    payload,
                    char,
                    closing_marker=BRACKETED_PASTE_END,
                )
                if "".join(payload[-len(BRACKETED_PASTE_END):]) == BRACKETED_PASTE_END:
                    del payload[-len(BRACKETED_PASTE_END):]
                    bracket_closed = True
                    if self.on_bracketed_paste is not None:
                        self.on_bracketed_paste("".join(payload))
                continue

            if (
                conpty_dispatch
                and char in "\r\n"
                and self._chunk_is_newline_only
                and self._chunk_wait_seconds >= self.submit_gap_seconds
            ):
                text = "".join(prefix).strip().lstrip("\x00\x15")
                return text or ""

            self._checked_append(
                prefix,
                char,
                closing_marker=BRACKETED_PASTE_START,
            )
            if "".join(prefix[-len(BRACKETED_PASTE_START):]) == BRACKETED_PASTE_START:
                del prefix[-len(BRACKETED_PASTE_START):]
                # ConPTY sends Ctrl+U before every dispatch to clear stale
                # editable input.  In raw mode it is data rather than a line-
                # editor command and must not become part of the agent prompt.
                prelude = "".join(prefix)
                if prelude.strip("\x00\x15\r\n\t "):
                    payload.extend(prefix)
                prefix.clear()
                bracketed = True
                continue

            if char in "\r\n" and not conpty_dispatch:
                text = "".join(prefix).strip().lstrip("\x00\x15")
                return text or ""


SendPrompt = Callable[[str, str, dict[str, Any]], dict[str, Any]]
WaitReply = Callable[[str, float], dict[str, Any] | None]


@dataclass
class HostHandshakeEcho:
    """Echo raw input in small safe chunks so a ConPTY host can send Enter."""

    output: TextIO
    chunk_size: int = 32
    max_visible_chars: int = 1024
    _buffer: list[str] = field(default_factory=list, init=False)
    _started: bool = field(default=False, init=False)
    _visible_chars: int = field(default=0, init=False)

    def reset(self) -> None:
        self._buffer.clear()
        self._started = False
        self._visible_chars = 0

    def feed(self, char: str) -> None:
        # BookOfEternityGMBridge starts each dispatch with Ctrl+U.  In raw
        # mode that is our reliable message-boundary signal and rearms the
        # bounded visibility echo for the next prompt.
        if char == "\x15":
            self.reset()
            return
        if self._visible_chars >= self.max_visible_chars:
            return
        # Do not replay C0 controls such as Ctrl+U or ESC.  Printable bytes of
        # a VT framing sequence are harmless; the actual ESC is gone, so they
        # cannot execute a terminal command.
        if not (char in "\r\n\t" or ord(char) >= 0x20 and char != "\x7f"):
            return
        self._visible_chars += 1
        self._buffer.append(char)
        if len(self._buffer) >= self.chunk_size or char in "\r\n":
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        if not self._started:
            self.output.write("\n")
            self._started = True
        self.output.write("".join(self._buffer))
        self.output.flush()
        self._buffer.clear()


def echo_prompt_for_host_handshake(prompt: str, output: TextIO) -> None:
    """Render a complete paste safely (public helper used by other adapters)."""
    echo = HostHandshakeEcho(
        output,
        chunk_size=max(1, len(prompt)),
        max_visible_chars=max(1, len(prompt)),
    )
    for char in prompt:
        echo.feed(char)
    echo.flush()
    output.write("\n")
    output.flush()


def _print_idle(output: TextIO) -> None:
    """Render markers understood by ordinary humans and ConPTY CLI hosts.

    The compatibility line is deliberately explicit rather than pretending
    to be Codex.  BookOfEternityGMBridge currently recognises the same
    ``gpt-* ·`` footer used by Codex when deciding that a CLI is idle.
    """
    output.write("state: READY\n")
    output.write("› \n")
    output.write("gpt-relay · Arena terminal transport\n")
    output.flush()


def run_terminal_loop(
    reader: PromptStreamReader,
    *,
    send_prompt: SendPrompt,
    wait_reply: WaitReply,
    output: TextIO,
    sender: str = "terminal-daemon",
    source: str = "terminal-relay",
    wait_slice: float = 25.0,
    reply_timeout: float = 0.0,
    now: Callable[[], float] = time.monotonic,
) -> int:
    """Run the persistent terminal-to-mailbox adapter.

    ``reply_timeout=0`` means wait indefinitely.  A timeout never fabricates a
    successful reply; it reports the timeout and returns to idle so a local
    daemon is not wedged forever.
    """
    output.write("=" * 60 + "\n")
    output.write("Arena Terminal Relay · OpenAI Codex-compatible transport\n")
    output.write("A running agent must poll relay.check; this process cannot summon one.\n")
    output.write("=" * 60 + "\n")
    _print_idle(output)

    sequence = 0
    while True:
        try:
            prompt = reader.read_prompt()
        except PromptTooLargeError as exc:
            output.write(f"\n[Relay error] {exc}\n")
            _print_idle(output)
            continue

        if prompt is None:
            return 0
        if not prompt:
            continue

        sequence += 1
        meta = {
            "transport": "terminal",
            "source": source,
            "sequence": sequence,
        }
        try:
            sent = send_prompt(prompt, sender, meta)
            message_id = str(sent.get("id") or "").strip()
            if not message_id:
                raise RuntimeError("relay send returned no message id")
        except Exception as exc:  # noqa: BLE001 - transport boundary
            output.write(f"\n[Relay error] could not queue prompt: {exc}\n")
            _print_idle(output)
            continue

        output.write(f"\n[Relay] queued message {message_id}\n")
        output.write(f"Working on terminal request #{sequence}\n")
        output.write("esc to interrupt\n")
        output.flush()

        deadline = now() + reply_timeout if reply_timeout > 0 else None
        while True:
            if deadline is None:
                wait = wait_slice
            else:
                remaining = deadline - now()
                if remaining <= 0:
                    output.write(
                        f"\n[Relay timeout] no agent reply for message {message_id}\n"
                    )
                    _print_idle(output)
                    break
                wait = min(wait_slice, remaining)

            try:
                reply = wait_reply(message_id, wait)
            except Exception as exc:  # noqa: BLE001 - keep the local CLI alive
                output.write(f"\n[Relay warning] reply poll failed: {exc}\n")
                output.flush()
                continue

            if reply is None:
                continue

            body = str(reply.get("body") or "").strip()
            reply_sender = str(reply.get("sender") or "agent")
            output.write(f"\n[Relay] reply from {reply_sender}:\n")
            output.write((body or "(empty reply)") + "\n")
            _print_idle(output)
            break
