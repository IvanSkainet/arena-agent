"""Guard: every Dashboard tab body must live inside the ``.main`` container.

Regression test for v4.96.0. A stray ``</div>`` in ``body-15-settings.html``
used to close ``.main`` early; because the loader concatenates body files in
manifest (filename) order, the six numerically-last tabs (mobile, live,
zerotier, proposals, transports, mcp) then landed as direct children of
``<body>`` instead of ``.main``. Since ``body{display:flex}``, those tabs were
laid out as sibling flex items to the right of an (empty, stretched) ``.main``
— the "content shifted right with an empty middle" cockpit bug on exactly the
tabs that followed the premature close.

The loader (``dashboard/index.html``) joins the shell + body files and lets the
HTML parser auto-close ``.main`` at the end of the fragment, so the invariant we
enforce here is: in the concatenated document, ``.main`` is opened by the shell
and NEVER closed inside the body files, and every ``tab-*`` element is opened
while ``.main`` is on the element stack. A future unbalanced ``</div>`` in any
body file breaks this and fails the test.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "dashboard" / "assets"


def _strip_non_layout(html: str) -> str:
    """Drop <script>/<style> blocks so stray '<div' inside JS/CSS template
    strings cannot corrupt the nesting stack."""
    html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.I)
    return html


def _concatenated_body() -> str:
    # Loader order = shell first, then body files sorted by filename (the
    # auto-generated manifest order). body-00-shell.html sorts first.
    parts = sorted(ASSETS.glob("body-*.html"))
    return "".join(_strip_non_layout(p.read_text(encoding="utf-8")) for p in parts)


class _Nesting(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.main_opened = False
        self.main_closed_inside = False
        self.tabs_outside_main: list[str] = []

    @staticmethod
    def _attrs_map(attrs) -> dict[str, str]:
        return {k: (v or "") for k, v in attrs}

    def _main_on_stack(self) -> bool:
        return any(t == "div" and "main" in a.get("class", "").split()
                   for t, a in self.stack)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "div":
            return
        amap = self._attrs_map(attrs)
        self.stack.append(("div", amap))
        if "main" in amap.get("class", "").split():
            self.main_opened = True
        tid = amap.get("id", "")
        if tid.startswith("tab-") and not self._main_on_stack():
            self.tabs_outside_main.append(tid)

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return
        # pop the nearest div on the stack
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == "div":
                closed = self.stack.pop(i)
                if "main" in closed[1].get("class", "").split():
                    self.main_closed_inside = True
                break


def test_main_opened_by_shell():
    n = _Nesting()
    n.feed(_concatenated_body())
    assert n.main_opened, "the shell must open <div class=\"main\">"


def test_main_not_closed_inside_body_files():
    """If a body file closes ``.main``, the tabs concatenated after it escape
    to ``<body>`` — the exact v4.96.0 bug. ``.main`` must stay open so the
    parser auto-closes it at the end of the fragment."""
    n = _Nesting()
    n.feed(_concatenated_body())
    assert not n.main_closed_inside, (
        "a body file closes <div class=\"main\"> prematurely; tabs after it "
        "escape to <body> and the cockpit layout shifts right")


def test_every_tab_inside_main():
    n = _Nesting()
    n.feed(_concatenated_body())
    assert not n.tabs_outside_main, (
        "these tabs are not nested inside .main (they would render as <body> "
        "flex siblings and shift the cockpit): " + ", ".join(n.tabs_outside_main))
