"""#540: a bridge that was killed or updated left its quick tunnel running and publicly reachable."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from arena.admin import cloudflared as cf_mod, cloudflared_orphans as orphans

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"
TUNNEL = ["cloudflared", "tunnel", "--url", URL]
LINUX_ONLY = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the stand-in is a symlink that names a process cloudflared")
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in is a script with a shebang line")


class FakeProc:
    """The part of psutil.Process the sweep reads."""

    defaults = {"name": "cloudflared", "cmdline": TUNNEL, "env": None, "ppid": 1, "created": 100.0, "deaf": False, "unreaped": False}

    def __init__(self, pid, **traits):
        self.pid = pid
        self.traits = {**self.defaults, **traits}
        self.info = {"name": self.traits["name"], "cmdline": self.traits["cmdline"]}
        self.unreaped = self.traits["unreaped"]
        self.signals = []
        self.running = True

    def environ(self):
        if self.traits["env"] is None:
            raise psutil.AccessDenied(self.pid)
        return self.traits["env"]

    def ppid(self):
        return self.traits["ppid"]

    def create_time(self):
        return self.traits["created"]

    def status(self):
        return psutil.STATUS_RUNNING if self.running else psutil.STATUS_ZOMBIE

    def terminate(self):
        self.signals.append("terminate")
        self.running = self.traits["deaf"]

    def kill(self):
        self.signals.append("kill")
        self.running = False


class Table:
    """Stand-in for the psutil module: `procs` is what the sweep iterates, `live` maps a PID to its start time."""

    Error, NoSuchProcess, STATUS_ZOMBIE = psutil.Error, psutil.NoSuchProcess, psutil.STATUS_ZOMBIE

    def __init__(self):
        self.procs, self.live = [], {}

    def process_iter(self, attrs=None):
        return list(self.procs)

    def Process(self, pid):  # noqa: N802 -- psutil's name
        if pid not in self.live:
            raise psutil.NoSuchProcess(pid)
        return SimpleNamespace(create_time=lambda: self.live[pid])

    def wait_procs(self, procs, timeout=None):
        return [], [proc for proc in procs if proc.running or proc.unreaped]

    def sweep(self, *, windows=False, **options):
        return orphans.sweep_orphaned_tunnels(PORT, psutil=self, parent_pid_survives=windows, **options)


@pytest.fixture(name="table")
def _table(monkeypatch):
    monkeypatch.delenv(orphans.SWEEP_ENV, raising=False)
    return Table()


def marked(port=PORT, owner=4242):
    return {orphans.OWNER_ENV: f"{port}:{owner}"}


def test_owner_env_marks_the_port_and_this_process(monkeypatch):
    monkeypatch.setenv("ARENA_TEST_PASSTHROUGH", "kept")
    env = orphans.owner_env(8799)
    assert env[orphans.OWNER_ENV] == f"8799:{os.getpid()}"
    assert env["ARENA_TEST_PASSTHROUGH"] == "kept"


def test_marked_tunnel_whose_bridge_is_gone_is_stopped(table):
    orphan = FakeProc(900, env=marked())
    table.procs = [orphan]
    assert table.sweep() == [900]
    assert orphan.signals == ["terminate"]


def test_marked_tunnel_whose_bridge_is_alive_is_left(table):
    owned = FakeProc(900, env=marked(owner=4242), created=100.0)
    table.procs, table.live = [owned], {4242: 50.0}
    assert table.sweep() == []
    assert owned.signals == []


def test_reused_owner_pid_does_not_protect_the_orphan(table):
    orphan = FakeProc(900, env=marked(owner=4242), created=100.0)
    table.procs, table.live = [orphan], {4242: 100.5}
    assert table.sweep() == [900]


@pytest.mark.parametrize("proc", [
    FakeProc(901, env=marked(port=8766)),
    FakeProc(902, env=marked(), cmdline=["cloudflared", "tunnel", "--url", "http://127.0.0.1:87650"]),
    FakeProc(903, env=marked(), cmdline=["cloudflared", "access", "--url", URL]),
    FakeProc(904, env=marked(), name="python"),
    FakeProc(905, env={orphans.OWNER_ENV: f"{PORT}:not-a-pid"}),
    FakeProc(906, env={}),
    FakeProc(907, env=None),
], ids=["other-port-mark", "other-port-url", "not-a-tunnel", "other-program", "broken-mark", "unmarked", "unreadable"])
def test_processes_that_are_not_this_bridges_orphans_are_left(table, proc):
    table.procs = [proc]
    assert table.sweep() == []
    assert proc.signals == []


def test_windows_stops_an_unmarked_tunnel_whose_parent_is_gone(table):
    legacy = FakeProc(900, name="cloudflared.exe", env={}, ppid=7836)
    table.procs = [legacy]
    assert table.sweep(windows=True) == [900]


def test_windows_leaves_an_unmarked_tunnel_whose_parent_is_alive(table):
    manual = FakeProc(900, name="cloudflared.exe", env={}, ppid=7836, created=100.0)
    table.procs, table.live = [manual], {7836: 50.0}
    assert table.sweep(windows=True) == []


def test_elsewhere_an_unmarked_tunnel_is_left_even_when_its_parent_is_gone(table):
    manual = FakeProc(900, env={}, ppid=7836)
    table.procs = [manual]
    assert table.sweep(windows=False) == []
    assert manual.signals == []


def test_tunnel_from_before_an_execv_restart_is_stopped(table):
    """os.execv keeps the PID, so the tunnel's owner looks alive: it is this very process."""
    mine = marked(owner=os.getpid())
    earlier_image, current = FakeProc(900, env=mine, created=100.0), FakeProc(901, env=mine, created=200.0)
    table.procs, table.live = [earlier_image, current], {os.getpid(): 50.0}
    assert table.sweep(keep_pid=901) == [900]
    assert current.signals == []


def test_tunnel_that_ignores_terminate_is_killed(table):
    stubborn = FakeProc(900, env=marked(), deaf=True)
    table.procs = [stubborn]
    assert table.sweep() == [900]
    assert stubborn.signals == ["terminate", "kill"]


def test_terminated_tunnel_that_nobody_reaps_counts_as_stopped(table):
    zombie = FakeProc(900, env=marked(), unreaped=True)
    table.procs = [zombie]
    assert table.sweep() == [900]
    assert zombie.signals == ["terminate"]


def test_tunnel_that_survives_kill_is_not_reported_as_stopped(table):
    immortal = FakeProc(900, env=marked(), deaf=True)
    immortal.kill = lambda: immortal.signals.append("kill")
    table.procs = [immortal]
    assert table.sweep() == []
    assert immortal.signals == ["terminate", "kill"]


def test_process_that_vanishes_during_inspection_is_skipped(table):
    gone = FakeProc(900, env=marked())
    gone.ppid = gone.create_time = lambda: (_ for _ in ()).throw(psutil.NoSuchProcess(900))
    gone.environ = lambda: (_ for _ in ()).throw(psutil.NoSuchProcess(900))
    table.procs = [gone]
    assert table.sweep() == []


@pytest.mark.parametrize("value", ["0", "false", "No", " off "])
def test_operator_can_switch_the_sweep_off(table, monkeypatch, value):
    orphan = FakeProc(900, env=marked())
    table.procs = [orphan]
    monkeypatch.setenv(orphans.SWEEP_ENV, value)
    assert table.sweep() == []
    assert orphan.signals == []


def startup_sweep(table, keep_pid=None):
    said = []
    orphans.sweep_at_startup(PORT, keep_pid, lambda text, *args: said.append(text % args), psutil=table, parent_pid_survives=False)
    return said


def test_startup_sweep_reports_what_it_stopped(table):
    table.procs = [FakeProc(900, env=marked()), FakeProc(901, env=marked())]
    assert startup_sweep(table) == [f"[Cloudflared] stopped 2 quick tunnel(s) left by an earlier bridge on port {PORT}: pid 900, 901"]


def test_startup_sweep_keeps_the_current_tunnel_and_stays_quiet(table):
    current = FakeProc(900, env=marked(owner=os.getpid()))
    table.procs = [current]
    assert not startup_sweep(table, keep_pid=900)
    assert current.signals == []


def test_startup_sweep_failure_does_not_stop_the_bridge(table):
    def unavailable(attrs=None):
        raise OSError("process table unavailable")

    table.process_iter = unavailable
    assert startup_sweep(table) == ["[Cloudflared] orphaned tunnel sweep failed: process table unavailable"]


ECHO_MARK = """#!{python}
import os, time
print("https://mark-" + os.environ.get("{env}", "none").replace(":", "-") + ".trycloudflare.com", flush=True)
time.sleep(120)
"""


@POSIX_ONLY
def test_started_tunnel_carries_the_owner_mark(tmp_path, monkeypatch):
    """A real child reports the mark it was started with, as a quick-tunnel URL."""
    stand_in = tmp_path / "cloudflared"
    stand_in.write_text(ECHO_MARK.format(python=sys.executable, env=orphans.OWNER_ENV), encoding="utf-8")
    stand_in.chmod(0o755)
    monkeypatch.setattr(cf_mod, "CLOUDFLARED_STATE", {"proc": None, "url": "", "log": []})
    try:
        result = cf_mod._start_cloudflared(str(stand_in), 8799, subprocess_kwargs=dict)
        assert result["url"] == f"https://mark-8799-{os.getpid()}.trycloudflare.com"
    finally:
        cf_mod.stop_cloudflared_for_shutdown()


STAND_IN = "import time; time.sleep(120)"
BRIDGE = """
import subprocess, sys, time
from arena.admin.cloudflared_orphans import owner_env
exe, port, mark, stay = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "marked", sys.argv[4] == "stay"
child = subprocess.Popen([exe, "-c", "import time; time.sleep(120)", "tunnel", "--url", f"http://127.0.0.1:{port}"],
                         env=owner_env(port) if mark else None, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(child.pid, flush=True)
if stay:
    time.sleep(120)
"""


@pytest.fixture(name="stand_in")
def _stand_in(tmp_path, monkeypatch):
    """Real processes named cloudflared: the interpreter behind a symlink, with a per-test port in its arguments."""
    exe = tmp_path / "cloudflared"
    exe.symlink_to(sys.executable)
    port = 20000 + os.getpid() % 20000
    started = []
    monkeypatch.delenv(orphans.SWEEP_ENV, raising=False)

    def bridge(mark="marked", stay="exit"):
        """Run a stand-in bridge that starts a tunnel, then exits or stays. Return the tunnel's PID."""
        proc = subprocess.Popen([sys.executable, "-c", BRIDGE, str(exe), str(port), mark, stay],
                                stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
        tunnel = int(proc.stdout.readline())
        started.extend([tunnel, proc.pid])
        if stay == "exit":
            proc.wait(timeout=30)
        wait_until_named(tunnel)
        return tunnel

    def own():
        child = subprocess.Popen([str(exe), "-c", STAND_IN, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                                 env=orphans.owner_env(port), stdin=subprocess.DEVNULL)
        started.append(child.pid)
        wait_until_named(child.pid)
        return child.pid

    yield SimpleNamespace(port=port, bridge=bridge, own=own)
    for pid in started:
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass


def runs(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def wait_until_named(pid):
    """The child is `python` until its exec completes; wait for the name the sweep looks for."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if psutil.Process(pid).name() == "cloudflared":
            return
        time.sleep(0.02)
    raise AssertionError(f"pid {pid} never became cloudflared")


@LINUX_ONLY
def test_live_orphan_of_a_dead_bridge_is_stopped(stand_in):
    orphan = stand_in.bridge()
    assert runs(orphan)
    assert orphans.sweep_orphaned_tunnels(stand_in.port) == [orphan]
    assert not runs(orphan)


@LINUX_ONLY
def test_live_tunnel_of_a_running_bridge_is_left(stand_in):
    owned = stand_in.bridge(stay="stay")
    assert orphans.sweep_orphaned_tunnels(stand_in.port) == []
    assert runs(owned)


@LINUX_ONLY
def test_live_tunnel_of_this_process_is_left_and_its_predecessor_stopped(stand_in):
    predecessor, current = stand_in.own(), stand_in.own()
    assert orphans.sweep_orphaned_tunnels(stand_in.port, keep_pid=current) == [predecessor]
    assert runs(current)


@LINUX_ONLY
def test_live_unmarked_tunnel_is_left(stand_in):
    manual = stand_in.bridge(mark="unmarked")
    assert orphans.sweep_orphaned_tunnels(stand_in.port) == []
    assert runs(manual)


class Tunnel:
    """A started tunnel as CLOUDFLARED_STATE holds it."""

    def __init__(self, *, deaf=False):
        self.deaf, self.signals, self.returncode = deaf, [], None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.signals.append("terminate")
        if not self.deaf:
            self.returncode = 0

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("cloudflared", timeout)
        return self.returncode

    def kill(self):
        self.signals.append("kill")
        self.returncode = -9


@pytest.fixture(name="running_tunnel")
def _running_tunnel(monkeypatch):
    tunnel = Tunnel()
    state = {"proc": tunnel, "url": "https://stand-in.trycloudflare.com", "log": []}
    monkeypatch.setattr(cf_mod, "CLOUDFLARED_STATE", state)
    return SimpleNamespace(tunnel=tunnel, state=state)


def test_shutdown_stops_the_tunnel_and_forgets_its_url(running_tunnel):
    cf_mod.stop_cloudflared_for_shutdown()
    assert running_tunnel.tunnel.signals == ["terminate"]
    assert running_tunnel.state["proc"] is None
    assert running_tunnel.state["url"] == ""


def test_shutdown_kills_a_tunnel_that_ignores_terminate(running_tunnel):
    running_tunnel.tunnel.deaf = True
    cf_mod.stop_cloudflared_for_shutdown()
    assert running_tunnel.tunnel.signals == ["terminate", "kill"]


def test_shutdown_without_a_tunnel_does_nothing(monkeypatch):
    monkeypatch.setattr(cf_mod, "CLOUDFLARED_STATE", {"proc": None, "url": "", "log": []})
    cf_mod.stop_cloudflared_for_shutdown()
    assert cf_mod.CLOUDFLARED_STATE == {"proc": None, "url": "", "log": []}


def lifecycle_runtime():
    from concurrent.futures import ThreadPoolExecutor

    from arena.lifecycle import LifecycleContext, make_lifecycle

    async def nothing(*_args):
        return None

    def no_op(*_args):
        return None

    pool = ThreadPoolExecutor(max_workers=1)
    return make_lifecycle(LifecycleContext(
        executor=pool, slow_executor=pool, init_memory_db=no_op, task_runner_loop=nothing, log_cleanup_loop=nothing,
        file_watch_loop=nothing, get_mission_schedule_loop=lambda: None, start_watchdog=no_op, stop_watchdog=no_op,
        stop_cdp_watcher=no_op, cdp_state={}, stop_grpc_server=nothing, stop_cluster_heartbeat=nothing,
        get_shutdown_event=lambda: None, version="test", log_info=no_op, log_debug=no_op))


def functions_stopping_the_tunnel():
    import ast

    from arena import lifecycle

    found, stack = set(), []

    class Visitor(ast.NodeVisitor):
        def function(self, node):
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_FunctionDef = visit_AsyncFunctionDef = function

        def visit_Call(self, node):
            if getattr(node.func, "id", None) == "stop_cloudflared_for_shutdown" and stack:
                found.add(stack[-1])
            self.generic_visit(node)

    with open(lifecycle.__file__, encoding="utf-8") as source:
        Visitor().visit(ast.parse(source.read()))
    return found


def test_signal_handler_stops_the_tunnel():
    """Parsed, not called: the handler arms os._exit, and aiohttp's cleanup may not run before it fires."""
    assert "signal_handler" in functions_stopping_the_tunnel()


def test_cleanup_stops_the_tunnel(running_tunnel):
    import asyncio

    from aiohttp import web

    asyncio.run(lifecycle_runtime().on_cleanup(web.Application()))
    assert running_tunnel.tunnel.signals == ["terminate"]
    assert running_tunnel.state["proc"] is None


@pytest.mark.parametrize(("current", "kept"), [(None, None), (SimpleNamespace(pid=77), 77)], ids=["no-tunnel-yet", "tunnel-running"])
def test_bridge_start_sweeps_before_it_starts_its_own_tunnel(monkeypatch, current, kept):
    import unified_bridge as ub
    from arena.admin import cloudflared_autostart

    order = []
    monkeypatch.setattr(orphans, "sweep_at_startup", lambda port, keep_pid, log_warning: order.append(("sweep", port, keep_pid)))
    monkeypatch.setattr(cloudflared_autostart, "run_autostart", lambda **options: order.append(("start", options["port"])))
    monkeypatch.setattr(cf_mod, "CLOUDFLARED_STATE", {"proc": current, "url": "", "log": []})
    ub._lifecycle_ctx.cloudflared_autostart()
    port = order[0][1]
    assert order == [("sweep", port, kept), ("start", port)]
