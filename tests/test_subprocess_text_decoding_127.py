"""Non-ASCII text must survive the trip through our subprocess helpers (#127).

Two halves of one defect, both reproduced by execution before the fix:

**The child.** ``bin/py_browser.py`` prints JSON with ``ensure_ascii=False``,
so stdout carries real non-ASCII characters. Python encodes stdout with the
*locale* encoding, and on a Windows console that is cp1251/cp866 -- so a page
containing CJK made the tool die with ``UnicodeEncodeError`` and exit 1. It
now pins its streams to UTF-8.

**The parent.** ``run_local``/``run_sd`` passed ``text=True`` with no
``encoding=``, so the child's UTF-8 bytes were decoded with the parent's
locale encoding. Under cp1251 that produced mojibake that *still parsed as
valid JSON*, so nothing raised and the corruption reached the caller
untouched; under an ASCII locale it raised ``UnicodeDecodeError`` outright.
``arena/inventory/runner.py:48-58`` already got this right and is the model.

The tests below drive the real helpers in a child interpreter with a hostile
locale, because neither half is observable in-process on a UTF-8 Linux box.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Cyrillic, CJK and typographic punctuation: the first two are absent from
# ASCII, the CJK run is also absent from cp1251, and the quotes catch the
# "looks fine, is actually cp1252" case.
SAMPLE = "Привет 日本語 «ёлка» — тире"

PY_BROWSER = REPO_ROOT / "bin" / "py_browser.py"


def _ascii_locale_env(**extra: str) -> dict[str, str]:
    """A parent environment whose preferred encoding is not UTF-8.

    Inherits the real environment first: a stripped env drops SYSTEMROOT and
    CPython cannot start on Windows.
    """
    env = dict(os.environ)
    env.update(
        {
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONCOERCECLOCALE": "0",
            "PYTHONUTF8": "0",
            "PYTHONIOENCODING": "ascii:replace",
        }
    )
    env.update(extra)
    return env


def _run_harness(harness: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run `harness` in a child interpreter, keeping its output as bytes.

    The harness reports through stderr as escaped ASCII so this test never
    depends on the very decoding it is trying to verify.
    """
    return subprocess.run(
        [sys.executable, "-c", harness],
        capture_output=True,
        timeout=120,
        cwd=str(REPO_ROOT),
        env=env,
    )


# --- the parent half: run_local / run_sd decoding ---------------------------

_PARENT_HARNESS = """
import sys
sys.path.insert(0, {root!r})
from {module} import {factory}
run_local = {build}
rc, out, err = run_local([sys.executable, {child!r}])
sys.stderr.buffer.write(
    ("rc=%s|out=%s" % (rc, out.strip().encode("unicode_escape").decode("ascii"))).encode("ascii")
)
"""


@pytest.fixture
def utf8_child(tmp_path: Path) -> str:
    """A child script that prints SAMPLE as UTF-8, whatever the locale."""
    script = tmp_path / "child_utf8.py"
    script.write_text(
        "import sys\n"
        'sys.stdout.reconfigure(encoding="utf-8")\n'
        f"print({SAMPLE!r})\n",
        encoding="utf-8",
    )
    return str(script)


@pytest.mark.parametrize(
    ("module", "factory", "build"),
    [
        ("arena.mcp.tool_utils", "make_run_local", "make_run_local(lambda: {})"),
        ("arena.mcp.standalone_common", "run_local", "run_local"),
    ],
)
def test_run_local_decodes_child_output_as_utf8(
    utf8_child, module, factory, build
):
    """`text=True` without `encoding=` decodes with the parent's locale.

    Under an ASCII locale that raised UnicodeDecodeError; under cp1251 it
    silently produced mojibake. Either way the caller lost the text.
    """
    harness = _PARENT_HARNESS.format(
        root=str(REPO_ROOT), module=module, factory=factory,
        build=build, child=utf8_child,
    )

    proc = _run_harness(harness, _ascii_locale_env())

    report = proc.stderr.decode("ascii", "replace")
    assert proc.returncode == 0, report
    assert "rc=0" in report, report
    # The harness escapes non-ASCII, so compare against the escaped form.
    expected = SAMPLE.encode("unicode_escape").decode("ascii")
    assert expected in report, f"text was corrupted in transit: {report}"


def test_the_decoding_kwargs_are_shared_not_retyped():
    """One constant per module, so a new call site cannot forget half of it."""
    from arena.mcp import standalone_common, tool_utils

    for module in (tool_utils, standalone_common):
        assert module._TEXT_DECODING == {"encoding": "utf-8", "errors": "replace"}, (
            f"{module.__name__} decodes with something other than replacing UTF-8"
        )


@pytest.mark.parametrize(
    "path", ["arena/mcp/tool_utils.py", "arena/mcp/standalone_common.py"]
)
def test_every_text_subprocess_in_these_helpers_pins_its_encoding(path):
    """A new `text=True` call here would silently reintroduce the bug."""
    import re

    src = (REPO_ROOT / path).read_text(encoding="utf-8")
    offenders = []
    for call in re.finditer(r"subprocess\.run\((?:[^()]|\([^()]*\))*\)", src, re.S):
        body = call.group(0)
        if "text=True" not in body:
            continue
        if "_TEXT_DECODING" not in body and "encoding=" not in body:
            line = src[: call.start()].count("\n") + 1
            offenders.append(f"{path}:{line}")
    assert not offenders, (
        "these subprocess.run calls decode with the locale encoding: "
        + ", ".join(offenders)
    )


# --- the child half: py_browser writing UTF-8 -------------------------------

_PY_BROWSER_HARNESS = r"""
import sys, json
sys.path.insert(0, {root!r})

# Read the markup from a file: passing it on the command line would make the
# *launcher* encode non-ASCII argv under the C locale and fail before the
# test starts.
_markup = open({markup_file!r}, encoding="utf-8").read()


class _Response:
    text = _markup
    headers = {{}}
    status_code = 200


import requests
requests.post = lambda *a, **k: _Response()
requests.get = lambda *a, **k: _Response()

sys.argv = ["py_browser.py", "search", "q", "--n", "1"]
exec(compile(open({script!r}, encoding="utf-8").read(), {script!r}, "exec"))
"""


def test_py_browser_prints_utf8_under_a_non_utf8_locale(tmp_path):
    """It prints ensure_ascii=False JSON, so its stdout must be UTF-8.

    With the locale in charge, a page carrying CJK raised UnicodeEncodeError
    inside the tool and it exited 1 -- the search returned nothing at all.
    """
    markup_file = tmp_path / "page.html"
    markup_file.write_text(
        f'<a class="result__a" href="https://x.test">{SAMPLE}</a>', encoding="utf-8"
    )
    harness = _PY_BROWSER_HARNESS.format(
        root=str(REPO_ROOT), markup_file=str(markup_file), script=str(PY_BROWSER)
    )

    proc = _run_harness(harness, _ascii_locale_env())

    stderr = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 0, stderr
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["results"][0]["title"] == SAMPLE, payload


def test_py_browser_reconfigures_stderr_too():
    """A traceback carrying a non-ASCII URL must not fail while printing."""
    src = PY_BROWSER.read_text(encoding="utf-8")
    assert "sys.stdout, sys.stderr" in src, (
        "only stdout was pinned to UTF-8; an error path can still die on encode"
    )


def test_py_browser_survives_a_stream_without_reconfigure():
    """`reconfigure` is TextIOWrapper-only; a redirected stream may lack it."""
    harness = (
        "import io, sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "sys.stdout = io.StringIO()\n"  # no .reconfigure
        "import requests\n"
        "class _R:\n"
        "    text = '<html><title>t</title></html>'\n"
        "    headers = {}\n"
        "    status_code = 200\n"
        "requests.get = lambda *a, **k: _R()\n"
        "sys.argv = ['py_browser.py', 'head', 'https://x.test']\n"
        "try:\n"
        f"    exec(compile(open({str(PY_BROWSER)!r}, encoding='utf-8').read(), 'pb', 'exec'))\n"
        "except SystemExit:\n"
        "    pass\n"
        "sys.stderr.write('survived')\n"
    )

    proc = _run_harness(harness, _ascii_locale_env())

    assert b"survived" in proc.stderr, proc.stderr.decode("utf-8", "replace")[-400:]
