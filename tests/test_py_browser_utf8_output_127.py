"""#127 -- browser.search threw away its results on a non-UTF-8 console.

Live reproduction on the bridge (Windows 10, cp1251 console):

    browser.search {"query": "атака титанов rutracker торрент"}  -> OK
    browser.search {"query": "атака титанов смотреть"}           -> ok: false,
      'charmap' codec can't encode character '\\U0001f4fa' in position 233

The first query works because every Cyrillic character is encodable in
cp1251; the second dies the moment a snippet carries U+1F4FA (a TV emoji,
routine on streaming sites). Nothing was wrong with the fetch -- the results
were valid UTF-8 and complete -- the command aborted while printing them.

The defect has two halves and both are covered here:

1. the child (`bin/py_browser.py`) printed `ensure_ascii=False` JSON to a
   stdout wearing the console codepage, so encoding raised and the process
   exited 1 with an empty stdout;
2. the parents (`run_local` / `run_sd`) read that output with `text=True` and
   no `encoding=`, so even a child that printed clean UTF-8 came back as
   mojibake on a cp1251 machine.

Half 2 is fixed with an opt-in (`utf8_child=True`) rather than a default: the
same two runners also carry `exec.run`, whose Windows output genuinely is in
the OEM codepage. Pinning utf-8 for everyone would have fixed the browser and
corrupted `dir`, so the tests below assert both directions.

`PYTHONIOENCODING=cp1251` reproduces half 1 on any platform: it is what
CPython uses to pick the stdout encoding, exactly as a Windows console
codepage does. Half 2 is reproduced by decoding with an explicit encoding.
"""
from __future__ import annotations

import ast
import http.server
import importlib.util
import json
import os
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY_BROWSER = ROOT / "bin" / "py_browser.py"

# U+1F4FA TELEVISION: the exact character from the issue.
TV = "\U0001f4fa"
SNIPPET = f"Смотреть {TV} онлайн"


def _load_py_browser():
    spec = importlib.util.spec_from_file_location("py_browser_127", PY_BROWSER)
    assert spec and spec.loader, PY_BROWSER
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ddg_stub():
    """A local stand-in for the DuckDuckGo HTML endpoint."""
    html = (
        "<html><body>"
        + "".join(
            f'<div class="result">'
            f'<a class="result__a" href="https://example.test/{i}">Аниме {i}</a>'
            f'<a class="result__snippet">{SNIPPET} серия {i}</a>'
            f"</div>"
            for i in range(3)
        )
        + "</body></html>"
    ).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib callback name
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        do_POST = do_GET  # noqa: N815 - stdlib callback name

        def log_message(self, *_args):  # noqa: D102 - silence the test log
            return

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def search_shim(tmp_path, ddg_stub):
    """Run the real py_browser with requests.get pinned at the stub."""
    shim = tmp_path / "shim.py"
    # cmd_search POSTs to DuckDuckGo; pin *both* verbs at the stub so a test
    # can never reach the real network (an earlier draft only pinned `get`
    # and silently scraped the live endpoint).
    shim.write_text(
        "import sys, requests\n"
        f"_STUB = {json.dumps(ddg_stub)}\n"
        "_get, _post = requests.get, requests.post\n"
        "requests.get = lambda url, **kw: _get(_STUB, **kw)\n"
        "requests.post = lambda url, **kw: _post(_STUB, **kw)\n"
        'sys.argv = ["py_browser.py"] + sys.argv[1:]\n'
        f"exec(open({json.dumps(str(PY_BROWSER))}, encoding='utf-8').read())\n",
        encoding="utf-8",
    )
    return shim


def _cp1251_env() -> dict[str, str]:
    """Inherit the environment, then force a non-UTF-8 stdout on the child."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1251"
    env.pop("PYTHONUTF8", None)
    return env


# --- half 1: the child must not lose its output ----------------------------


def test_search_survives_an_emoji_on_a_cp1251_console(search_shim):
    proc = subprocess.run(
        [sys.executable, str(search_shim), "search", "атака титанов", "--n", "3"],
        capture_output=True,
        timeout=60,
        env=_cp1251_env(),
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    stdout = proc.stdout.decode("utf-8")
    assert TV in stdout, "the emoji from the snippet did not survive"
    payload = json.loads(stdout)
    assert len(payload["results"]) == 3, payload
    assert TV in payload["results"][0]["snippet"]


def test_the_failure_mode_from_the_issue_is_gone(search_shim):
    """The old build exited 1 with an empty stdout and a charmap error."""
    proc = subprocess.run(
        [sys.executable, str(search_shim), "search", "атака титанов", "--n", "3"],
        capture_output=True,
        timeout=60,
        env=_cp1251_env(),
    )
    stderr = proc.stderr.decode("utf-8", "replace")

    assert proc.stdout, "stdout was empty -- results were fetched and dropped"
    assert "charmap" not in stderr, stderr
    assert "codec can't encode" not in stderr, stderr


def test_cyrillic_only_results_are_unaffected(search_shim):
    """The issue notes the Cyrillic-only query already worked; keep it working."""
    proc = subprocess.run(
        [sys.executable, str(search_shim), "search", "аниме", "--n", "1"],
        capture_output=True,
        timeout=60,
        env=_cp1251_env(),
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert "Смотреть" in proc.stdout.decode("utf-8")


def test_stdout_is_utf8_not_escaped_ascii(search_shim):
    """`ensure_ascii=False` is deliberate: fix the stream, not the payload.

    Escaping to ASCII would also stop the crash, but it would make every
    Cyrillic snippet unreadable for the caller. Assert the real bytes.
    """
    proc = subprocess.run(
        [sys.executable, str(search_shim), "search", "аниме", "--n", "1"],
        capture_output=True,
        timeout=60,
        env=_cp1251_env(),
    )

    assert proc.returncode == 0
    assert TV.encode("utf-8") in proc.stdout, "emoji was escaped or dropped"
    assert b"\\u041c" not in proc.stdout, "output fell back to \\uXXXX escapes"


def test_error_reporting_also_survives_a_non_ascii_message():
    """The `except` branch prints to stderr; it must not crash while doing so."""
    proc = subprocess.run(
        [sys.executable, str(PY_BROWSER), "read", f"http://invalid.{TV}.test/"],
        capture_output=True,
        timeout=60,
        env=_cp1251_env(),
    )

    stderr = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 1, stderr
    assert "charmap" not in stderr, stderr
    payload = json.loads(stderr.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert payload["cmd"] == "read"


def test_force_utf8_io_is_called_before_anything_prints():
    """A reconfigure after the first write would be too late."""
    source = PY_BROWSER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    first = main.body[0]

    assert isinstance(first, ast.Expr), ast.dump(first)
    assert isinstance(first.value, ast.Call)
    assert getattr(first.value.func, "id", None) == "_force_utf8_io"


def test_force_utf8_io_tolerates_a_stream_that_cannot_be_reconfigured():
    """Under pytest's capture, stdout may be a plain object with no reconfigure."""
    mod = _load_py_browser()

    class Bare:
        pass

    class Angry:
        def reconfigure(self, **_kwargs):
            raise ValueError("detached buffer")

    for stream in (Bare(), Angry()):
        original_out, original_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stream, stream
        try:
            mod._force_utf8_io()  # must not raise
        finally:
            sys.stdout, sys.stderr = original_out, original_err


def test_a_stream_without_reconfigure_does_not_stop_the_other_one():
    """stdout may be capturable while stderr is not, or the reverse.

    Skipping the odd stream must `continue`, not `break`: with `break` the
    first bare stream left stderr on the console codepage, which is exactly
    where the charmap error was reported from.
    """
    mod = _load_py_browser()
    seen: list[str] = []

    class Bare:
        pass

    class Recorder:
        def reconfigure(self, **_kwargs):
            seen.append("reconfigured")

    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Bare(), Recorder()
    try:
        mod._force_utf8_io()
    finally:
        sys.stdout, sys.stderr = original_out, original_err

    assert seen == ["reconfigured"], (
        "stderr was skipped because an unreconfigurable stdout ended the loop"
    )


def test_force_utf8_io_asks_for_utf8_and_a_replacement_policy():
    mod = _load_py_browser()
    seen: list[dict] = []

    class Recorder:
        def reconfigure(self, **kwargs):
            seen.append(kwargs)

    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Recorder(), Recorder()
    try:
        mod._force_utf8_io()
    finally:
        sys.stdout, sys.stderr = original_out, original_err

    assert seen == [
        {"encoding": "utf-8", "errors": "replace"},
        {"encoding": "utf-8", "errors": "replace"},
    ], seen


# --- half 2: the parent must not mangle what the child printed -------------


def _child_printing(tmp_path: Path) -> Path:
    child = tmp_path / "child.py"
    # `repr`, not `json.dumps`: the latter escapes an astral character into a
    # surrogate pair, which Python source reads back as two lone surrogates.
    child.write_text(
        "import sys\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        f"print({SNIPPET!r})\n",
        encoding="utf-8",
    )
    return child


def test_run_local_decodes_our_own_child_as_utf8(tmp_path, monkeypatch):
    """Without a pinned encoding this came back as `РЎРјРѕС‚СЂРµС‚СЊ`."""
    from arena.mcp.tool_utils import make_run_local

    captured: dict = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):
        captured.update(kwargs)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    run_local = make_run_local(lambda: {})
    rc, out, err = run_local([sys.executable, str(_child_printing(tmp_path))],
                             timeout=60, utf8_child=True)

    assert rc == 0, err
    assert captured.get("encoding") == "utf-8", captured
    assert captured.get("errors") == "replace", captured
    assert out.strip() == SNIPPET
    assert "Р" not in out or TV in out, f"mojibake: {out!r}"


def test_run_local_keeps_the_windows_subprocess_flags(tmp_path, monkeypatch):
    """The encoding must be added to the platform kwargs, not replace them."""
    from arena.mcp.tool_utils import make_run_local

    captured: dict = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):
        captured.update(kwargs)
        return real_run(argv, **{k: v for k, v in kwargs.items() if k != "creationflags"})

    monkeypatch.setattr(subprocess, "run", spy)
    run_local = make_run_local(lambda: {"creationflags": 0x08000000})
    run_local([sys.executable, "-c", "print(1)"], timeout=60, utf8_child=True)

    assert captured.get("creationflags") == 0x08000000, captured
    assert captured.get("encoding") == "utf-8", captured


def test_an_arbitrary_command_is_not_forced_into_utf8(tmp_path, monkeypatch):
    """`exec.run` output is whatever the OEM codepage says; do not overrule it.

    The first cut of this fix pinned utf-8 inside the runners themselves. That
    fixes the browser and breaks everyone else: `Каталог` emitted as cp866 by
    `cmd /c dir` decodes to replacement characters under utf-8.
    """
    from arena.mcp.tool_utils import make_run_local

    captured: dict = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):
        captured.update(kwargs)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    rc, out, err = make_run_local(lambda: {})([sys.executable, "-c", "print(1)"], timeout=60)

    assert "encoding" not in captured, captured
    assert "errors" not in captured, captured
    # `text=True` is what keeps this a str once the encoding is gone: without
    # it the caller silently starts receiving bytes.
    assert captured.get("text") is True, captured
    assert isinstance(out, str) and isinstance(err, str), (type(out), type(err))
    assert (rc, out.strip()) == (0, "1")


def test_the_oem_output_this_protects_would_really_be_destroyed():
    """Proof the default above is not cargo cult: decode cp866 as utf-8."""
    oem = "Каталог".encode("cp866")

    assert oem.decode("utf-8", "replace") != "Каталог"
    assert "\ufffd" in oem.decode("utf-8", "replace")


def test_a_caller_supplied_encoding_is_not_clobbered(tmp_path, monkeypatch):
    """`f(**UTF8_CHILD_IO, **kwargs)` raises TypeError on a duplicate key."""
    from arena.mcp.tool_utils import make_run_local

    captured: dict = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):
        captured.update(kwargs)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    run_local = make_run_local(lambda: {"encoding": "cp1251"})
    run_local([sys.executable, "-c", "print(1)"], timeout=60, utf8_child=True)

    assert captured.get("encoding") == "cp1251", captured


@pytest.mark.parametrize("name", ["run_local", "run_sd"])
def test_the_standalone_dispatcher_reuses_the_shared_runner(name):
    """standalone_common used to re-implement these byte for byte.

    Two copies meant #127 had to be fixed twice, and CodeQL carried a separate
    dismissed alert for each. They come from one factory now.
    """
    common = importlib.import_module("arena.mcp.standalone_common")
    utils = importlib.import_module("arena.mcp.tool_utils")

    runner = getattr(common, name)
    factory = getattr(utils, f"make_{name}")

    assert runner.__qualname__ == f"{factory.__name__}.<locals>.{name}", (
        f"standalone_common.{name} is a second copy: {runner.__qualname__}"
    )


def test_the_standalone_dispatcher_has_no_subprocess_call_of_its_own():
    """A future edit must not quietly re-grow the duplicate."""
    tree = ast.parse((ROOT / "arena/mcp/standalone_common.py").read_text(encoding="utf-8"))
    calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func).startswith("subprocess.")
    ]

    assert not calls, f"standalone_common.py grew its own subprocess call at {calls}"


def test_every_py_browser_launch_asks_for_utf8():
    """The opt-in is worthless if a call site forgets it.

    Both dispatchers shell out to `bin/py_browser.py`; each such call must
    pass `utf8_child=True`, which is what makes half 2 of #127 stay fixed.
    """
    offenders = []
    for rel in ("arena/mcp/tool_browser.py", "arena/mcp/standalone_tools.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if ast.unparse(node.func) != "run_local":
                continue
            if "py_browser.py" not in ast.unparse(node):
                continue
            if any(kw.arg == "utf8_child" and getattr(kw.value, "value", None) is True
                   for kw in node.keywords):
                continue
            offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        "py_browser prints UTF-8; these launches read it with the console "
        "codepage:\n  " + "\n  ".join(offenders)
    )
