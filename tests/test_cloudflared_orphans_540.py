"""#540: a bridge that was killed or updated left its quick tunnel running and publicly reachable."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import psutil
import pytest
from aiohttp import web

from arena import cli, lifecycle
from arena.admin import cloudflared as cf_mod, cloudflared_orphans as orphans

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"
TUNNEL = ["cloudflared", "tunnel", "--url", URL]
STOPPED_900 = f"[Cloudflared] stopped 1 quick tunnel(s) left by an earlier bridge on port {PORT}: pid 900"
LINUX_ONLY = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="relies on a script's name becoming the process name")
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in is a script with a shebang line")


class FakeProc:
    """The part of psutil.Process the sweep reads."""

    defaults = {"name": "cloudflared", "cmdline": TUNNEL, "env": None, "ppid": 1, "created": 100.0,
                "deaf": False, "immortal": False, "unreaped": False, "vanished": False}

    def __init__(self, pid, **traits):
        """Describe one process; `traits` override `defaults`."""
        self.pid = pid
        self.traits = {**self.defaults, **traits}
        self.info = {"name": self.traits["name"], "cmdline": self.traits["cmdline"]}
        self.signals = []
        self.running = True

    def _query(self, trait):
        if self.traits["vanished"]:
            raise psutil.NoSuchProcess(self.pid)
        return self.traits[trait]

    def environ(self):
        env = self._query("env")
        if env is None:
            raise psutil.AccessDenied(self.pid)
        return env

    def ppid(self):
        return self._query("ppid")

    def create_time(self):
        return self._query("created")

    def status(self):
        return psutil.STATUS_RUNNING if self.running else psutil.STATUS_ZOMBIE

    def terminate(self):
        self.signals.append("terminate")
        self.running = self.traits["deaf"]

    def kill(self):
        self.signals.append("kill")
        self.running = self.traits["immortal"]


class Table:
    """Stand-in for the psutil module: `procs` is what the sweep iterates, `live` maps a PID to its start time."""

    Error, NoSuchProcess, STATUS_ZOMBIE = psutil.Error, psutil.NoSuchProcess, psutil.STATUS_ZOMBIE

    def __init__(self):
        """Start with an empty process table."""
        self.procs, self.live = [], {}

    def process_iter(self, attrs=None):
        return list(self.procs)

    def Process(self, pid):  # noqa: N802 -- psutil's name
        if pid not in self.live:
            raise psutil.NoSuchProcess(pid)
        return SimpleNamespace(create_time=lambda: self.live[pid])

    def wait_procs(self, procs, timeout=None):
        return [], [proc for proc in procs if proc.running or proc.traits["unreaped"]]

    def sweep(self, *, windows=False, **options):
        return orphans.sweep_orphaned_tunnels(PORT, psutil=self, parent_pid_survives=windows, **options)


@pytest.fixture(name="table")
def _table(monkeypatch):
    monkeypatch.delenv(orphans.SWEEP_ENV, raising=False)
    return Table()


def marked(port=PORT, owner=4242):
    return {orphans.OWNER_ENV: f"{port}:{owner}"}


def recorder():
    """Return a list and a logger that appends each formatted message to it."""
    said = []
    return said, lambda text, *args: said.append(text % args)


# --- which tunnel is an orphan -------------------------------------------------

def test_owner_env_marks_the_port_and_this_process(monkeypatch):
    monkeypatch.setenv("ARENA_TEST_PASSTHROUGH", "kept")
    env = orphans.owner_env(8799)
    assert env[orphans.OWNER_ENV] == f"8799:{os.getpid()}"
    assert env["ARENA_TEST_PASSTHROUGH"] == "kept"


def test_owner_env_marks_an_environment_the_caller_supplies():
    supplied = {"ONLY": "this", orphans.OWNER_ENV: "1:1"}
    assert orphans.owner_env(8799, supplied) == {"ONLY": "this", orphans.OWNER_ENV: f"8799:{os.getpid()}"}
    assert supplied[orphans.OWNER_ENV] == "1:1"


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


def test_tunnel_from_before_an_execv_restart_is_stopped(table):
    """os.execv keeps the PID, so the tunnel's owner looks alive: it is this very process."""
    mine = marked(owner=os.getpid())
    earlier_image, current = FakeProc(900, env=mine, created=100.0), FakeProc(901, env=mine, created=200.0)
    table.procs, table.live = [earlier_image, current], {os.getpid(): 50.0}
    assert table.sweep(keep_pid=901) == [900]
    assert current.signals == []


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
    assert manual.signals == []


def test_elsewhere_an_unmarked_tunnel_is_left_even_when_its_parent_is_gone(table):
    manual = FakeProc(900, env={}, ppid=7836)
    table.procs = [manual]
    assert table.sweep(windows=False) == []


@pytest.mark.parametrize("windows", [False, True])
def test_process_that_vanishes_during_inspection_is_skipped(table, windows):
    gone = FakeProc(900, env=marked(), vanished=True)
    table.procs = [gone]
    assert table.sweep(windows=windows) == []
    assert gone.signals == []


# --- stopping ------------------------------------------------------------------

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
    immortal = FakeProc(900, env=marked(), deaf=True, immortal=True)
    table.procs = [immortal]
    assert table.sweep() == []
    assert immortal.signals == ["terminate", "kill"]


@pytest.mark.parametrize("value", ["0", "false", "No", " off "])
def test_operator_can_switch_the_sweep_off(table, monkeypatch, value):
    orphan = FakeProc(900, env=marked())
    table.procs = [orphan]
    monkeypatch.setenv(orphans.SWEEP_ENV, value)
    assert table.sweep() == []
    assert orphan.signals == []


def test_without_psutil_nothing_is_swept(monkeypatch):
    monkeypatch.delenv(orphans.SWEEP_ENV, raising=False)
    monkeypatch.setattr(orphans, "_load_psutil", lambda: None)
    assert orphans.sweep_orphaned_tunnels(PORT) == []


# --- the sweep as the bridge runs it ---------------------------------------------

def test_sweep_reports_what_it_stopped(table):
    table.procs = [FakeProc(900, env=marked()), FakeProc(901, env=marked())]
    said, log = recorder()
    orphans.sweep_and_report(PORT, None, log, psutil=table, parent_pid_survives=False)
    assert said == [f"[Cloudflared] stopped 2 quick tunnel(s) left by an earlier bridge on port {PORT}: pid 900, 901"]


def test_sweep_that_stops_nothing_stays_quiet(table):
    table.procs = [FakeProc(900, env={})]
    said, log = recorder()
    orphans.sweep_and_report(PORT, None, log, psutil=table, parent_pid_survives=False)
    assert not said


def test_bridge_sweep_spares_the_tunnel_this_process_holds(table, monkeypatch):
    mine = marked(owner=os.getpid())
    current = FakeProc(901, env=mine)
    table.procs = [FakeProc(900, env=mine), current]
    monkeypatch.setattr(cf_mod, "CLOUDFLARED_STATE", {"proc": SimpleNamespace(pid=901), "url": "", "log": []})
    said, log = recorder()
    cf_mod.sweep_tunnels_left_by_earlier_bridge(PORT, log, psutil=table, parent_pid_survives=False)
    assert said == [STOPPED_900]
    assert current.signals == []


def test_bridge_sweep_before_any_tunnel_was_started(table, monkeypatch):
    table.procs = [FakeProc(900, env=marked())]
    monkeypatch.setattr(cf_mod, "CLOUDFLARED_STATE", {"proc": None, "url": "", "log": []})
    said, log = recorder()
    cf_mod.sweep_tunnels_left_by_earlier_bridge(PORT, log, psutil=table, parent_pid_survives=False)
    assert said == [STOPPED_900]


class ServeStopped(Exception):
    """Raised by the stand-in token resolver: the step of `serve` right after the sweep."""


def test_serve_sweeps_the_port_it_will_listen_on(monkeypatch):
    """The port comes from the config file, so the sweep has to run after the file is applied."""
    def resolve_token(_token):
        raise ServeStopped

    swept = []
    ctx = SimpleNamespace(ensure_session_env=lambda: None, load_config_file=lambda: {"port": 9321}, cdp_state={},
                          resolve_token=resolve_token, log_info=lambda *_args: None)
    monkeypatch.setattr(cli, "_reap_orphan_mcp_servers", lambda _ctx: None)
    monkeypatch.setattr(cf_mod, "sweep_tunnels_left_by_earlier_bridge", lambda port, _log: swept.append(port))
    args = argparse.Namespace(background=False, port=8765, token=None)
    with pytest.raises(ServeStopped):
        cli._serve_runtime(args, ctx)
    assert swept == [9321]


def test_failing_sweep_does_not_keep_the_bridge_from_starting(monkeypatch):
    def broken(_port, _log):
        raise RuntimeError("process table unavailable")

    monkeypatch.setattr(cf_mod, "sweep_tunnels_left_by_earlier_bridge", broken)
    said, log = recorder()
    cli._sweep_quick_tunnels(SimpleNamespace(log_info=log), PORT)
    assert said == ["[Cloudflared] startup sweep of orphaned tunnels skipped: process table unavailable"]


# --- real processes ------------------------------------------------------------

# The stand-in reports the mark it runs with, and ARENA_TEST_TUNNEL_TAG, as a quick-tunnel URL. A test that needs
# another mark, or none, names it in ARENA_TEST_TUNNEL_MARK: the stand-in then replaces its own image, so the new
# environment is the one visible from outside.
STAND_IN = """#!{python}
import os, sys, time
override = os.environ.pop("ARENA_TEST_TUNNEL_MARK", None)
if override is not None:
    os.environ.pop("{env}", None)
    if override:
        os.environ["{env}"] = override
    os.execv(sys.argv[0], sys.argv)
tag = os.environ.get("ARENA_TEST_TUNNEL_TAG", "untagged")
print("https://mark-" + os.environ.get("{env}", "none").replace(":", "-") + "-" + tag + ".trycloudflare.com", flush=True)
time.sleep(120)
"""


@pytest.fixture(name="start_tunnel")
def _start_tunnel(tmp_path, monkeypatch):
    """Start stand-in tunnels through the production starter and stop them afterwards."""
    stand_in = tmp_path / "cloudflared"
    stand_in.write_text(STAND_IN.format(python=sys.executable, env=orphans.OWNER_ENV), encoding="utf-8")
    stand_in.chmod(0o700)
    monkeypatch.delenv(orphans.SWEEP_ENV, raising=False)
    started = []

    def start(port, mark=None, env=None):
        if mark is None:
            monkeypatch.delenv("ARENA_TEST_TUNNEL_MARK", raising=False)
        else:
            monkeypatch.setenv("ARENA_TEST_TUNNEL_MARK", mark)
        monkeypatch.setattr(cf_mod, "CLOUDFLARED_STATE", {"proc": None, "url": "", "log": []})
        result = cf_mod._start_cloudflared(str(stand_in), port, subprocess_kwargs=lambda: {} if env is None else {"env": env})
        started.append(cf_mod.CLOUDFLARED_STATE["proc"])
        return SimpleNamespace(pid=started[-1].pid, url=result.get("url"))

    yield start
    for proc in started:
        proc.kill()
        proc.wait(timeout=10)


def reported(mark, tag="untagged"):
    """Return the URL a stand-in prints when it runs with this mark and tag."""
    return f"https://mark-{mark}-{tag}.trycloudflare.com"


def own_port():
    """Return a port number no other test worker puts into its stand-in's command line."""
    return 20000 + os.getpid() % 20000


def unused_pid():
    pid = 4_000_000
    while psutil.pid_exists(pid):
        pid -= 1
    return pid


def runs(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


@POSIX_ONLY
def test_started_tunnel_carries_the_owner_mark(start_tunnel):
    assert start_tunnel(8799).url == reported(f"8799-{os.getpid()}")


@POSIX_ONLY
def test_started_tunnel_keeps_the_callers_environment_and_gets_the_mark(start_tunnel, monkeypatch):
    monkeypatch.setenv("ARENA_TEST_TUNNEL_TAG", "inherited")
    supplied = {"ARENA_TEST_TUNNEL_TAG": "supplied", orphans.OWNER_ENV: "1:1"}
    assert start_tunnel(8799, env=supplied).url == reported(f"8799-{os.getpid()}", "supplied")


@LINUX_ONLY
def test_live_orphan_of_a_dead_bridge_is_stopped(start_tunnel):
    port = own_port()
    orphan = start_tunnel(port, mark=f"{port}:{unused_pid()}")
    assert runs(orphan.pid)
    assert orphans.sweep_orphaned_tunnels(port) == [orphan.pid]
    assert not runs(orphan.pid)


@LINUX_ONLY
def test_live_tunnel_of_another_running_bridge_is_left(start_tunnel):
    port = own_port()
    owned = start_tunnel(port, mark=f"{port}:{os.getppid()}")
    assert owned.url == reported(f"{port}-{os.getppid()}")
    assert orphans.sweep_orphaned_tunnels(port) == []
    assert runs(owned.pid)


@LINUX_ONLY
def test_live_tunnel_of_this_process_is_left_and_its_predecessor_stopped(start_tunnel):
    port = own_port()
    predecessor, current = start_tunnel(port), start_tunnel(port)
    assert orphans.sweep_orphaned_tunnels(port, keep_pid=current.pid) == [predecessor.pid]
    assert runs(current.pid)
    assert not runs(predecessor.pid)


@LINUX_ONLY
def test_live_unmarked_tunnel_is_left(start_tunnel):
    port = own_port()
    manual = start_tunnel(port, mark="")
    assert manual.url == reported("none")
    assert orphans.sweep_orphaned_tunnels(port) == []
    assert runs(manual.pid)


# --- shutdown ------------------------------------------------------------------

class Tunnel:
    """A started tunnel as CLOUDFLARED_STATE holds it."""

    def __init__(self, *, deaf=False):
        """Create a running tunnel; a deaf one ignores terminate."""
        self.deaf, self.signals, self.returncode = deaf, [], None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.signals.append("terminate")
        if not self.deaf:
            self.returncode = 0

    def wait(self, timeout=None):
        if self.returncode is None:
            raise TimeoutError(f"still running after {timeout} s")
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
    assert not running_tunnel.state["url"]


def test_shutdown_kills_a_tunnel_that_ignores_terminate(running_tunnel):
    running_tunnel.tunnel.deaf = True
    cf_mod.stop_cloudflared_for_shutdown()
    assert running_tunnel.tunnel.signals == ["terminate", "kill"]


def test_shutdown_without_a_tunnel_does_nothing(monkeypatch):
    monkeypatch.setattr(cf_mod, "CLOUDFLARED_STATE", {"proc": None, "url": "", "log": []})
    cf_mod.stop_cloudflared_for_shutdown()
    assert cf_mod.CLOUDFLARED_STATE == {"proc": None, "url": "", "log": []}


def test_the_lifecycle_helper_stops_the_tunnel(running_tunnel):
    lifecycle._stop_quick_tunnel()
    assert running_tunnel.tunnel.signals == ["terminate"]
    assert running_tunnel.state["proc"] is None


def test_both_shutdown_hooks_stop_the_tunnel_before_their_own_work(running_tunnel):
    """The signal handler runs here without its os._exit timer: the wrapper is given stand-in hooks."""
    seen = []

    async def cleanup(_app):
        seen.append(("cleanup", running_tunnel.state["proc"]))

    def on_signal(sig, _frame):
        seen.append((sig, running_tunnel.state["proc"]))

    runtime = lifecycle._tunnel_stopped_first(lifecycle.LifecycleRuntime(no_op, cleanup, on_signal))
    assert runtime.on_startup is no_op
    runtime.signal_handler(15, None)
    assert running_tunnel.tunnel.signals == ["terminate"]
    running_tunnel.state["proc"] = other = Tunnel()
    asyncio.run(runtime.on_cleanup(web.Application()))
    assert other.signals == ["terminate"]
    assert seen == [(15, None), ("cleanup", None)]


async def nothing(*_args):
    return None


def no_op(*_args):
    return None


def test_cleanup_stops_the_tunnel(running_tunnel):
    pool = ThreadPoolExecutor(max_workers=1)
    runtime = lifecycle.make_lifecycle(lifecycle.LifecycleContext(
        executor=pool, slow_executor=pool, init_memory_db=no_op, task_runner_loop=nothing, log_cleanup_loop=nothing,
        file_watch_loop=nothing, get_mission_schedule_loop=no_op, start_watchdog=no_op, stop_watchdog=no_op,
        stop_cdp_watcher=no_op, cdp_state={}, stop_grpc_server=nothing, stop_cluster_heartbeat=nothing,
        get_shutdown_event=no_op, version="test", log_info=no_op, log_debug=no_op))
    asyncio.run(runtime.on_cleanup(web.Application()))
    assert running_tunnel.tunnel.signals == ["terminate"]
    assert running_tunnel.state["proc"] is None
