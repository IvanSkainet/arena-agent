"""Importing the push module writes nothing; the server prepares the queue."""

# `arena/mcp/ws_push.py` used to create `<agent home>/logs/ws_notify.queue` in its
# module body. Every importer therefore wrote under the agent home -- including
# `scripts/mcp_ws_server.py --help` and every pytest worker during collection,
# where no fixture has run yet and the home is the real `~/arena-bridge`.
#
# Under two xdist workers that became a failure: both import the module at the
# same moment, both `openat(O_CREAT)` the same new name, and macOS answers one of
# them ENOENT (golang/go#81246). The hosted macOS runner hit it in one of the
# first parallel runs: the module failed to import in one worker, so the workers
# disagreed on the collected tests and the session ended before running any.

from __future__ import annotations

import runpy
import sys
from types import SimpleNamespace

import pytest

from arena.mcp import ws_push, ws_server


def test_importing_the_push_module_creates_nothing_under_the_agent_home(tmp_path, monkeypatch):
    """The module body only computes the queue path."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    # A second, private execution of the module body: the copy other tests
    # share stays as it is, with its subscribers and its own queue path.
    namespace = runpy.run_path(ws_push.__file__, run_name="ws_push_import_probe")
    assert namespace["NOTIFY_QUEUE"] == tmp_path / "logs" / "ws_notify.queue"
    assert list(tmp_path.iterdir()) == []


class _Listener:
    """A listening socket whose first accept ends the serve loop."""

    def __init__(self, events):
        self.events = events

    def setsockopt(self, *args):
        """Accept the reuse-address option."""

    def bind(self, address):
        """Record that the server reached its socket."""
        self.events.append(("bind", address))

    def listen(self, backlog):
        """Accept the backlog."""

    def accept(self):
        """Stop the loop the way Ctrl+C does."""
        raise KeyboardInterrupt

    def close(self):
        """Record the shutdown."""
        self.events.append(("close",))


@pytest.fixture(name="served")
def _served(monkeypatch):
    """Run `main()` against recorded stand-ins for the queue, thread and socket."""
    events = []

    def thread(target, daemon):
        events.append(("thread", target, daemon))
        return SimpleNamespace(start=lambda: events.append(("start",)))

    monkeypatch.setattr(sys, "argv", ["mcp_ws_server.py", "--port", "0"])
    monkeypatch.setattr(ws_server, "threading", SimpleNamespace(Thread=thread))
    monkeypatch.setattr(ws_server, "socket", SimpleNamespace(
        socket=lambda *args: _Listener(events),
        AF_INET=0, SOCK_STREAM=0, SOL_SOCKET=0, SO_REUSEADDR=0))
    monkeypatch.setattr(ws_server, "_prepare_notify_queue",
                        lambda path: events.append(("prepare", path)))
    return events


def test_the_server_prepares_the_queue_before_the_watcher_and_the_socket(served, capsys):
    """The watcher reads the queue's size first, so the file has to exist by then."""
    ws_server.main()
    assert served == [
        ("prepare", ws_server.NOTIFY_QUEUE),
        ("thread", ws_server._notify_watcher, True),
        ("start",),
        ("bind", ("127.0.0.1", 0)),
        ("close",),
    ]
    assert "ws://127.0.0.1:0" in capsys.readouterr().out


def test_a_queue_that_cannot_be_prepared_stops_the_server(served, monkeypatch):
    """Refused in the foreground, not swallowed inside the watcher thread."""
    def refuse(path):
        raise OSError("refusing a linked notification queue")

    monkeypatch.setattr(ws_server, "_prepare_notify_queue", refuse)
    with pytest.raises(OSError, match="linked notification queue"):
        ws_server.main()
    assert served == []


def test_help_does_not_prepare_the_queue(served, monkeypatch, capsys):
    """Asking for usage is not starting a server."""
    monkeypatch.setattr(sys, "argv", ["mcp_ws_server.py", "--help"])
    with pytest.raises(SystemExit) as stopped:
        ws_server.main()
    assert stopped.value.code == 0
    assert served == []
    assert "--port" in capsys.readouterr().out
