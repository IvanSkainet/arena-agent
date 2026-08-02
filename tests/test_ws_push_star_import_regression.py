"""WebSocket push actually pushes.

The bug this pins was real, silent, and years old.

`arena/mcp/ws_push.py` and `ws_client.py` did `from arena.mcp.ws_frames import
*` and then called `_send_text`, `_http_handshake`, `_recv_frame`,
`_send_frame`. A star import **never binds underscore-prefixed names** unless
the source module declares `__all__`, and ws_frames does not. So those calls
raised NameError every time.

Nothing crashed visibly, which is why it survived: `_broadcast` wraps each
subscriber send in `except Exception`, so the NameError was caught, the
subscriber was appended to `dead`, and every WebSocket client was silently
unsubscribed on the first notification. The feature reported success and
delivered nothing.

The tests below therefore assert on *delivery* -- bytes on the socket, the
subscriber still registered afterwards -- rather than on "no exception". An
exception-free run was exactly the broken behaviour.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.mcp import ws_client, ws_frames, ws_push  # noqa: E402


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _clean_subs():
    with ws_push.SUBS_LOCK:
        saved = {k: set(v) for k, v in ws_push.SUBS.items()}
        ws_push.SUBS.clear()
    yield
    with ws_push.SUBS_LOCK:
        ws_push.SUBS.clear()
        ws_push.SUBS.update(saved)


def test_broadcast_actually_writes_to_the_subscriber():
    sock = FakeSocket()
    with ws_push.SUBS_LOCK:
        ws_push.SUBS.setdefault("topic", set()).add(sock)

    ws_push._broadcast("topic", {"a": 1})

    assert sock.sent, "broadcast produced no bytes -- the send call is not bound"
    payload = b"".join(sock.sent)
    assert b"notify" in payload
    assert b"topic" in payload


def test_broadcast_does_not_silently_unsubscribe_a_healthy_client():
    """The actual damage the old bug caused."""
    sock = FakeSocket()
    with ws_push.SUBS_LOCK:
        ws_push.SUBS.setdefault("topic", set()).add(sock)

    ws_push._broadcast("topic", {"a": 1})

    with ws_push.SUBS_LOCK:
        still_there = sock in ws_push.SUBS.get("topic", set())
    assert still_there, "a healthy subscriber was dropped as dead"


def test_a_genuinely_broken_subscriber_is_still_dropped():
    """The dead-client path must keep working; this is not a blanket disable."""
    class Broken(FakeSocket):
        def sendall(self, data: bytes) -> None:
            raise ConnectionResetError("gone")

    good, bad = FakeSocket(), Broken()
    with ws_push.SUBS_LOCK:
        ws_push.SUBS.setdefault("topic", set()).update({good, bad})

    ws_push._broadcast("topic", {"a": 1})

    with ws_push.SUBS_LOCK:
        remaining = ws_push.SUBS.get("topic", set())
    assert good in remaining
    assert bad not in remaining


# ---------------------------------------------------------------------------
# The import contract that made it possible
# ---------------------------------------------------------------------------

UNDERSCORE_API = ("_send_text", "_send_frame", "_recv_frame", "_http_handshake")


def test_star_import_still_does_not_provide_the_underscore_api():
    """Documents *why* the explicit imports are required, not optional."""
    namespace: dict = {}
    exec("from arena.mcp.ws_frames import *", namespace)  # noqa: S102
    for name in UNDERSCORE_API:
        assert name not in namespace, (
            f"{name} now arrives via the star import; the explicit import may "
            "be redundant, but check for an added __all__ first"
        )
    for name in UNDERSCORE_API:
        assert hasattr(ws_frames, name), f"{name} vanished from ws_frames"


@pytest.mark.parametrize("module,names", [
    (ws_push, ("_send_text",)),
    (ws_client, UNDERSCORE_API),
])
def test_each_module_binds_every_underscore_helper_it_calls(module, names):
    for name in names:
        assert hasattr(module, name), (
            f"{module.__name__} calls {name} but never binds it -- the star "
            "import does not provide underscore names"
        )


def test_no_module_calls_an_unbound_underscore_helper():
    """Catch the same class of bug appearing in a sibling module."""
    offenders = []
    for path in sorted((REPO / "arena" / "mcp").glob("ws_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id.startswith("_")
            and not node.func.id.startswith("__")
        }
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        imported = {
            (alias.asname or alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        for name in sorted(called - defined - imported):
            offenders.append(f"{path.name}: calls {name}, neither defined nor imported")
    assert offenders == [], offenders


def test_skill_runner_can_fire_its_hooks():
    """Fifth instance of the same blind spot.

    arena/skills/cli_run.py called `_fire_hook` on the FIRST line of
    run_skill(), relying on `from cli_common import *` -- which never provides
    underscore names. Every `skill run` therefore raised NameError before it
    did anything. Asserting the call path, not just the binding.
    """
    import types

    from arena.skills import cli_run

    assert hasattr(cli_run, "_fire_hook"), "the hook helper is unbound again"
    rc = cli_run.run_skill(types.SimpleNamespace(name="definitely-not-a-skill",
                                                 skill_args=[]))
    assert rc == 2, f"expected the not-found exit code, got {rc}"
