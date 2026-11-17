"""Python browser extraction must work without optional HTML/CSS packages."""
from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
PY_BROWSER = ROOT / "bin" / "py_browser.py"
CHECK = TestCase()


def _load_py_browser():
    spec = importlib.util.spec_from_file_location("py_browser_test", PY_BROWSER)
    if spec is None or spec.loader is None:
        raise AssertionError("browser entrypoint is not loadable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_html_extraction_needs_no_optional_parser(monkeypatch):
    original = builtins.__import__

    def limited_import(name, *args, **kwargs):
        if name.split(".")[0] in ("bs4", "soupsieve", "lxml"):
            raise ImportError("optional HTML/CSS package unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", limited_import)
    mod = _load_py_browser()
    page = mod._extract("<html><title>ok</title><p>Hello</p></html>")
    CHECK.assertEqual(page.title, "ok")
    CHECK.assertIn("Hello", page.text(" "))


def test_dump_preserves_json_fields_and_link_text(monkeypatch, capsys):
    import json
    from types import SimpleNamespace

    mod = _load_py_browser()
    response = SimpleNamespace(text='<title>Title</title><p>Hello</p><a href="/x">link</a>',
                               url="https://example.test/final", status_code=200)
    monkeypatch.setattr(mod, "_get", lambda _url: response)
    CHECK.assertEqual(mod.cmd_dump("https://example.test", None), 0)
    CHECK.assertEqual(json.loads(capsys.readouterr().out), {
        "url": response.url, "status": 200, "title": "Title", "text": "Title\nHello\nlink",
        "links": [{"text": "link", "href": "/x"}],
    })


def test_read_works_without_readability(monkeypatch, capsys):
    import json
    import sys
    from types import SimpleNamespace

    mod = _load_py_browser()
    monkeypatch.setitem(sys.modules, "readability", None)
    response = SimpleNamespace(text='<title>Привет</title><p>мир</p>', url="https://example.test")
    monkeypatch.setattr(mod, "_get", lambda _url: response)
    CHECK.assertEqual(mod.cmd_read(response.url), 0)
    CHECK.assertEqual(json.loads(capsys.readouterr().out), {
        "url": response.url, "title": "Привет", "text": "Привет\nмир",
    })
