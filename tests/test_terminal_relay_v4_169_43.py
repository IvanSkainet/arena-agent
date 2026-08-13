"""v4.169.43: generic daemon -> terminal -> relay -> agent transport.

The live Book of Eternity test exposed two holes hidden by the earlier file-only
E2E: the daemon's prompt is multiline bracketed paste, while boe_cli used
``readline()``; and no generic transport carried that prompt into Agent Mode.
These tests pin message framing, correlation, and the exact idle/busy transition
that a ConPTY host observes.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
from pathlib import Path

import pytest

from arena.relay import store, terminal as terminal_module
from arena.relay.terminal import (
    BRACKETED_PASTE_END,
    BRACKETED_PASTE_START,
    BufferedTextChunkReader,
    HostHandshakeEcho,
    PromptStreamReader,
    PromptTooLargeError,
    echo_prompt_for_host_handshake,
    raw_terminal_input,
    run_terminal_loop,
    windows_raw_input_mode,
)


def test_plain_terminal_line_is_one_prompt() -> None:
    reader = PromptStreamReader(io.StringIO("process the build\r\n"))
    assert reader.read_prompt() == "process the build"


def test_raw_conpty_control_frames_multiline_prompt_until_delayed_enter() -> None:
    chunks = iter(["\x15Process turn #2\nMain groups:\n- one", "\r"])
    clock = iter([0.0, 0.001, 0.001, 0.30])
    reader = PromptStreamReader(
        io.StringIO(""),
        read_chunk=lambda: next(chunks),
        now=lambda: next(clock),
    )
    assert reader.read_prompt() == "Process turn #2\nMain groups:\n- one"


def test_raw_conpty_eof_before_delayed_enter_is_not_delivered() -> None:
    chunks = iter(["\x15partial\nprompt", ""])
    clock = iter([0.0, 0.001, 0.001, 0.30])
    reader = PromptStreamReader(
        io.StringIO(""),
        read_chunk=lambda: next(chunks),
        now=lambda: next(clock),
    )
    assert reader.read_prompt() is None


def test_chunked_reader_preserves_framing_split_across_chunks() -> None:
    chunks = iter(["\x15\x1b[2", "00~long\n", "prompt\x1b[20", "1~\r", ""])
    reader = PromptStreamReader(io.StringIO(""), read_chunk=lambda: next(chunks))
    assert reader.read_prompt() == "long\nprompt"


def test_binary_chunk_decoder_preserves_split_utf8_character() -> None:
    encoded = "я".encode("utf-8")

    class FakeBinary:
        def __init__(self) -> None:
            self.parts = iter([encoded[:1], encoded[1:] + b"\r", b""])

        def read1(self, _size: int) -> bytes:
            return next(self.parts)

    class FakeText:
        encoding = "utf-8"
        buffer = FakeBinary()

        def read(self, _size: int) -> str:
            raise AssertionError("binary read1 should be used")

    chunks = BufferedTextChunkReader(FakeText())
    reader = PromptStreamReader(FakeText(), read_chunk=chunks.read_chunk)
    assert reader.read_prompt() == "я"


def test_multiline_bracketed_paste_is_one_prompt_not_many_lines() -> None:
    body = "Process turn #2\nRead input/turn_request.json\nThen write output files."
    stream = io.StringIO(BRACKETED_PASTE_START + body + BRACKETED_PASTE_END + "\r")
    reader = PromptStreamReader(stream)
    assert reader.read_prompt() == body
    assert reader.read_prompt() is None


def test_bracketed_paste_requires_final_enter() -> None:
    body = "first\nsecond"
    without_enter = io.StringIO(BRACKETED_PASTE_START + body + BRACKETED_PASTE_END)
    assert PromptStreamReader(without_enter).read_prompt() is None


def test_host_handshake_callback_sees_full_long_paste_before_submission() -> None:
    body = "A" * 4096 + "\n" + "B" * 4096
    observed: list[str] = []
    stream = io.StringIO(
        "\x15" + BRACKETED_PASTE_START + body + BRACKETED_PASTE_END + "\r"
    )
    reader = PromptStreamReader(stream, on_bracketed_paste=observed.append)
    assert reader.read_prompt() == body
    assert observed == [body]


def test_raw_console_mode_disables_line_and_echo_but_keeps_other_bits() -> None:
    original = 0x0001 | 0x0002 | 0x0004 | 0x0010
    changed = windows_raw_input_mode(original)
    assert changed & 0x0001  # processed input / Ctrl+C remains enabled
    assert changed & 0x0010
    assert not changed & 0x0002
    assert not changed & 0x0004
    assert changed & 0x0200


def test_raw_terminal_input_is_a_noop_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(terminal_module.os, "name", "posix")
    with raw_terminal_input() as enabled:
        assert enabled is False


def test_handshake_echo_strips_terminal_controls_not_visible_text() -> None:
    output = io.StringIO()
    echo_prompt_for_host_handshake("safe\x1b[2J\x00\nnext", output)
    rendered = output.getvalue()
    assert "safe[2J" in rendered
    assert "next" in rendered
    assert "\x1b" not in rendered
    assert "\x00" not in rendered


def test_streaming_handshake_echo_flushes_before_a_long_prompt_finishes() -> None:
    output = io.StringIO()
    echo = HostHandshakeEcho(output, chunk_size=4)
    for char in "1234still-arriving":
        echo.feed(char)
    assert "1234" in output.getvalue()
    echo.flush()
    assert "still-arriving" in output.getvalue()


def test_handshake_echo_is_bounded_even_when_the_prompt_is_huge() -> None:
    output = io.StringIO()
    echo = HostHandshakeEcho(output, chunk_size=128, max_visible_chars=512)
    for char in "x" * 50_000:
        echo.feed(char)
    echo.flush()
    assert 500 <= len(output.getvalue()) <= 520


def test_ctrl_u_rearms_handshake_echo_for_the_next_dispatch() -> None:
    output = io.StringIO()
    echo = HostHandshakeEcho(output, chunk_size=4, max_visible_chars=4)
    for char in "first":
        echo.feed(char)
    echo.flush()
    echo.feed("\x15")
    for char in "next":
        echo.feed(char)
    echo.flush()
    assert "firs" in output.getvalue()
    assert "next" in output.getvalue()


def test_truncated_bracketed_paste_is_never_delivered() -> None:
    stream = io.StringIO(BRACKETED_PASTE_START + "do half a dangerous thing")
    assert PromptStreamReader(stream).read_prompt() is None


def test_terminal_prompt_limit_is_fail_closed() -> None:
    reader = PromptStreamReader(io.StringIO("123456\n"), max_chars=4)
    with pytest.raises(PromptTooLargeError, match="4"):
        reader.read_prompt()


def test_eof_delivers_a_final_plain_line() -> None:
    reader = PromptStreamReader(io.StringIO("last command"))
    assert reader.read_prompt() == "last command"


def test_loop_round_trips_through_the_real_mailbox(tmp_path: Path) -> None:
    relay_root = tmp_path / "relay"
    prompt = "Process turn #3\nUse the repair packet if validation fails."
    stdin = io.StringIO(BRACKETED_PASTE_START + prompt + BRACKETED_PASTE_END + "\r")
    stdout = io.StringIO()
    seen_meta: list[dict] = []

    def send_prompt(body: str, sender: str, meta: dict) -> dict:
        sent = store.send_message(relay_root, body, sender=sender, meta=meta)
        seen_meta.append(meta)
        # Simulate an already-running agent claiming the packet and replying.
        claimed = store.claim_next(relay_root)
        assert claimed is not None
        assert claimed.id == sent.id
        assert claimed.body == prompt
        store.post_reply(relay_root, claimed.id, "files written; terminal signal last")
        return {"id": sent.id}

    def wait_reply(message_id: str, _wait: float) -> dict | None:
        replies = store.read_replies(relay_root, in_reply_to=message_id)
        return replies[0].to_dict() if replies else None

    code = run_terminal_loop(
        PromptStreamReader(stdin),
        send_prompt=send_prompt,
        wait_reply=wait_reply,
        output=stdout,
        sender="boe-daemon",
        source="live-game",
    )

    assert code == 0
    assert seen_meta == [
        {"transport": "terminal", "source": "live-game", "sequence": 1}
    ]
    rendered = stdout.getvalue()
    assert "Working on terminal request #1" in rendered
    assert "esc to interrupt" in rendered
    assert "files written; terminal signal last" in rendered
    assert rendered.count("state: READY") == 2  # startup + correlated reply


def test_idle_marker_comes_after_busy_marker_only_after_reply() -> None:
    stdin = io.StringIO("one request\n")
    stdout = io.StringIO()
    waits = 0

    def send_prompt(_body: str, _sender: str, _meta: dict) -> dict:
        return {"id": "msg-1"}

    def wait_reply(_message_id: str, _wait: float) -> dict | None:
        nonlocal waits
        waits += 1
        if waits == 1:
            return None
        return {"body": "done", "sender": "agent"}

    run_terminal_loop(
        PromptStreamReader(stdin),
        send_prompt=send_prompt,
        wait_reply=wait_reply,
        output=stdout,
    )
    rendered = stdout.getvalue()
    busy = rendered.index("Working on terminal request")
    reply = rendered.index("reply from agent", busy)
    idle = rendered.index("state: READY", reply)
    assert busy < reply < idle
    assert "gpt-relay · Arena terminal transport" in rendered[idle:]


def test_send_failure_does_not_claim_success_or_wedge_next_prompt() -> None:
    stdin = io.StringIO("first\nsecond\n")
    stdout = io.StringIO()
    sent: list[str] = []

    def send_prompt(body: str, _sender: str, _meta: dict) -> dict:
        sent.append(body)
        if body == "first":
            raise OSError("bridge offline")
        return {"id": "second-id"}

    def wait_reply(_message_id: str, _wait: float) -> dict | None:
        return {"body": "second accepted", "sender": "agent"}

    run_terminal_loop(
        PromptStreamReader(stdin),
        send_prompt=send_prompt,
        wait_reply=wait_reply,
        output=stdout,
    )
    assert sent == ["first", "second"]
    rendered = stdout.getvalue()
    assert "could not queue prompt: bridge offline" in rendered
    assert "second accepted" in rendered


def test_empty_lines_are_not_queued() -> None:
    stdin = io.StringIO("\r\n\nactual\n")
    stdout = io.StringIO()
    bodies: list[str] = []

    def send_prompt(body: str, _sender: str, _meta: dict) -> dict:
        bodies.append(body)
        return {"id": "only"}

    run_terminal_loop(
        PromptStreamReader(stdin),
        send_prompt=send_prompt,
        wait_reply=lambda _id, _wait: {"body": "ok"},
        output=stdout,
    )
    assert bodies == ["actual"]


def test_release_local_token_is_found_without_putting_it_on_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release ZIP keeps bin/ and token.txt under the same arena-bridge root."""
    cli_path = Path(__file__).parents[1] / "bin" / "arena-relay"
    loader = importlib.machinery.SourceFileLoader("arena_relay_cli_test", str(cli_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    release_root = tmp_path / "arena-bridge"
    release_root.mkdir()
    (release_root / "token.txt").write_text("local-release-token\n", encoding="utf-8")
    monkeypatch.delenv("ARENA_TOKEN", raising=False)
    monkeypatch.setattr(module, "ROOT", release_root)

    assert module._token() == "local-release-token"
