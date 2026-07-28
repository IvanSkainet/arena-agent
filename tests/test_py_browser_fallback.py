"""v4.105.1 -- py_browser falls back when lxml is unavailable."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_BROWSER = ROOT / "bin" / "py_browser.py"


def _load_py_browser():
    spec = importlib.util.spec_from_file_location("py_browser_test", PY_BROWSER)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_soup_falls_back_to_html_parser(monkeypatch):
    mod = _load_py_browser()
    real_bs = mod.BeautifulSoup

    def fake_bs(markup, parser):
        if parser == "lxml":
            raise mod.FeatureNotFound("no lxml")
        return real_bs(markup, parser)

    monkeypatch.setattr(mod, "BeautifulSoup", fake_bs)
    soup = mod._soup("<html><title>ok</title><p>Hello</p></html>")
    assert soup.title.string == "ok"
    assert "Hello" in soup.get_text(" ")
