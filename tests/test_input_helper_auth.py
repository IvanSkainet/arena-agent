"""The Input Helper must not serve keystrokes to unauthenticated callers.

`arena/input_helper/helper_server.py` is an HTTP server that runs in the
user's interactive desktop session and exposes `/click`, `/move`, `/type`,
`/key` and `/launch`. It was at 17% coverage.

Bug #54 -- authentication was optional and off by default:

    parser.add_argument("--token", type=str, default="")
    ...
    def _check_auth(self):
        if not _TOKEN:
            return True          # <- everything is public

Started with no arguments -- which is exactly what the MCP tool's own
hint told people to do -- the helper served every endpoint to any local
caller. Verified by execution: with `_TOKEN` empty,
`POST /launch {"path": "/bin/true"}` reached `subprocess.Popen` and only
failed because `CREATE_NEW_CONSOLE` is Windows-only. On Windows the
process would have started.

"Binds to 127.0.0.1 only" is not authentication. A browser tab running
hostile JavaScript can POST to localhost; so can any other process or
user on the machine. And this particular loopback port is a remote
control for the desktop -- mouse, keyboard, arbitrary process launch --
so leaving it open is local privilege escalation with extra steps.

The token comparison also used `==`, which leaks a shared secret byte by
byte to anyone who can time the response. It guards keystroke injection,
so it gets `hmac.compare_digest`.

Sabotage record (mandatory per AGENTS.md):
  1. restoring `if not _TOKEN: return True`
     -> test_an_empty_token_refuses_every_request fails.
  2. removing the startup refusal in `main()`
     -> test_the_helper_refuses_to_start_without_a_token fails.
  3. swapping `hmac.compare_digest` back to `==`
     -> test_the_token_comparison_is_constant_time fails.
"""
from __future__ import annotations

import ctypes
import importlib.util
import json
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "arena" / "input_helper" / "helper_server.py"


def _load_helper():
    """Import the helper on any OS.

    It calls into `ctypes.windll` at request time, not import time, but
    the module-level `ctypes.windll.user32` lookups still need to resolve
    on Linux and macOS runners -- the behaviour under test (authentication)
    has nothing to do with the platform, so it must be testable on all of
    them.
    """
    if not hasattr(ctypes, "windll"):
        stub = types.SimpleNamespace(
            user32=types.SimpleNamespace(**{
                name: (lambda *a, **kw: 0) for name in (
                    "SendInput", "SetCursorPos", "GetSystemMetrics",
                    "VkKeyScanW", "EnumWindows", "GetWindowTextW",
                    "GetWindowTextLengthW", "SetForegroundWindow",
                    "IsWindowVisible", "GetForegroundWindow")}),
            kernel32=types.SimpleNamespace(GetLastError=lambda: 0))
        ctypes.windll = stub  # type: ignore[attr-defined]

    spec = importlib.util.spec_from_file_location("_arena_helper_under_test",
                                                  HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def helper():
    return _load_helper()


@pytest.fixture()
def serving(helper):
    """Run the handler on an ephemeral port with a chosen token."""
    servers = []

    def start(token: str) -> int:
        helper._TOKEN = token
        server = HTTPServer(("127.0.0.1", 0), helper.InputHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        time.sleep(0.05)
        return server.server_address[1]

    yield start
    for server in servers:
        server.shutdown()


def _request(port: int, path: str, *, body=None, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


# ---------------------------------------------------------------------------
# The open-by-default hole.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,body", [
    ("/health", None),
    ("/launch", {"path": "/bin/true"}),
    ("/click", {"x": 1, "y": 1}),
    ("/type", {"text": "hello"}),
    ("/key", {"name": "a"}),
    ("/move", {"x": 1, "y": 1}),
])
def test_an_empty_token_refuses_every_request(serving, path, body):
    """No token configured must mean no service, not free service."""
    port = serving("")

    status, payload = _request(port, path, body=body)

    assert status == 503, (
        f"{path} answered {status} with no token configured; before "
        "v4.164.0 this endpoint was simply public"
    )
    assert "without a token" in payload


@pytest.mark.parametrize("path,body", [
    ("/health", None),
    ("/launch", {"path": "/bin/true"}),
    ("/type", {"text": "hello"}),
])
def test_a_wrong_token_is_refused(serving, path, body):
    port = serving("correct-horse-battery-staple")

    status, payload = _request(port, path, body=body, token="wrong")

    assert status == 401
    assert "unauthorized" in payload


def test_no_token_header_is_refused(serving):
    port = serving("correct-horse-battery-staple")

    status, _payload = _request(port, "/health")

    assert status == 401


def test_the_right_token_still_works(serving):
    """A guard that blocks the legitimate caller is a guard people remove."""
    token = "correct-horse-battery-staple"
    port = serving(token)

    status, payload = _request(port, "/health", token=token)

    assert status == 200
    assert json.loads(payload)["ok"] is True


# ---------------------------------------------------------------------------
# Startup.
# ---------------------------------------------------------------------------

def test_the_helper_refuses_to_start_without_a_token(tmp_path):
    """Running it bare must fail loudly, not listen quietly."""
    env = {"PATH": "/usr/bin:/bin", "SYSTEMROOT": "C:\\Windows"}
    result = subprocess.run(
        [sys.executable, str(HELPER), "--port", "19999"],
        capture_output=True, text=True, timeout=60, env=env,
    )

    assert result.returncode == 2, (
        "the helper started (or crashed differently) without a token; it "
        f"exited {result.returncode}: {result.stderr[:300]}"
    )
    assert "will not run" in result.stderr
    assert "listening" not in result.stdout.lower()


def test_the_startup_error_says_how_to_fix_it():
    """Refusing without a remedy just gets worked around."""
    source = HELPER.read_text(encoding="utf-8")

    assert "ARENA_INPUT_HELPER_TOKEN" in source
    assert "token_urlsafe" in source, (
        "the refusal should show how to generate a token, or the next "
        "person will pick 'test' as theirs"
    )


def test_exit_code_reaches_the_shell():
    """`main()` returning 2 is useless if __main__ discards it."""
    source = HELPER.read_text(encoding="utf-8")
    assert "raise SystemExit(main())" in source, (
        "a supervisor reading only the exit status would treat the "
        "refusal to start as a clean shutdown"
    )


# ---------------------------------------------------------------------------
# Comparison shape.
# ---------------------------------------------------------------------------

def test_the_token_comparison_is_constant_time():
    """`==` on a secret leaks it to anyone who can time the response."""
    source = HELPER.read_text(encoding="utf-8")

    assert "hmac.compare_digest" in source
    for lineno, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "_TOKEN" in stripped and "==" in stripped:
            pytest.fail(
                f"helper_server.py:{lineno} compares the token with `==`: "
                f"{stripped}"
            )


def test_the_mcp_hint_does_not_teach_the_unsafe_invocation():
    """The old hint told people to run it with no token at all."""
    hint_source = (Path(__file__).resolve().parents[1] / "arena" / "mcp"
                   / "tool_input_helper.py").read_text(encoding="utf-8")

    if "helper_server.py" in hint_source:
        assert "ARENA_INPUT_HELPER_TOKEN" in hint_source, (
            "the tool hint shows how to start the helper but omits the "
            "token, which is the invocation that used to be wide open"
        )
