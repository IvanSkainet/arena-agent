"""Static structural checks for the Browser tab redesign.

Guards the ids the 09-*.js loaders read from and enforces the
scoped-CSS discipline the redesign arc established.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-06-browser.html"


@pytest.fixture(scope="module")
def body_html() -> str:
    return _BODY.read_text(encoding="utf-8")


PRESERVED_IDS = [
    # Search card (09-browser-search.js)
    "searchQuery", "searchCount", "searchResults",
    # URL Tools card (09b/c/d-browser-*.js)
    "readUrl", "readResult", "dumpResult", "headResult",
]


@pytest.mark.parametrize("id_", PRESERVED_IDS)
def test_preserved_id_present(body_html: str, id_: str):
    assert f'id="{id_}"' in body_html, (
        f"Browser redesign removed #{id_} -- would silently break "
        f"09-browser-*.js loaders"
    )


def test_tab_wrapper_and_h1(body_html: str):
    assert 'id="tab-browser"' in body_html
    assert '<h1>Browser</h1>' in body_html


def test_all_button_handlers_preserved(body_html: str):
    for fn in ("browserSearch", "browserRead", "browserDump",
               "browserFetch", "browserHead", "browserScreenshot"):
        assert f"{fn}()" in body_html, f"missing onclick={fn}()"


def test_scoped_css_only(body_html: str):
    style_blocks = re.findall(r"<style>(.*?)</style>", body_html,
                              flags=re.DOTALL)
    assert style_blocks

    def strip_comments(css):
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    def strip_at_rules(css):
        out, i = [], 0
        while i < len(css):
            if css[i] == "@":
                open_pos = css.find("{", i)
                if open_pos < 0:
                    break
                depth, j = 1, open_pos + 1
                while j < len(css) and depth > 0:
                    if css[j] == "{":
                        depth += 1
                    elif css[j] == "}":
                        depth -= 1
                    j += 1
                i = j
                continue
            out.append(css[i])
            i += 1
        return "".join(out)

    for block in style_blocks:
        clean = strip_at_rules(strip_comments(block))
        for m in re.finditer(r"([^{}]+)\{[^{}]*\}", clean):
            for sel in m.group(1).split(","):
                sel = sel.strip()
                if not sel or sel.startswith("@"):
                    continue
                assert sel.startswith("#tab-browser"), (
                    f"Unscoped selector in Browser <style>: {sel!r}"
                )


def test_palette_vars_scoped(body_html: str):
    assert "#tab-browser{" in body_html or "#tab-browser {" in body_html
    for var in ("--br-tint-green", "--br-tint-blue", "--br-tint-purple"):
        assert var in body_html


def test_section_badges_advertise_endpoints(body_html: str):
    """Both cards get a section-badge that names the endpoint they
    hit. Missing one = a UX regression that's easy to reintroduce."""
    assert '/v1/browser/search' in body_html
    assert 'read · dump · fetch · head · shot' in body_html


def test_result_containers_use_scoped_class(body_html: str):
    """Every result container gets class="br-result" so the
    empty-hide rule (:empty{display:none}) fires. Prevents blank
    boxes stacking under the toolbar before any tool has run."""
    for id_ in ("searchResults", "readResult", "dumpResult", "headResult"):
        # look near the id
        idx = body_html.find(f'id="{id_}"')
        assert idx > 0
        window = body_html[max(0, idx - 200):idx + 200]
        assert "br-result" in window, (
            f'#{id_} must carry class="br-result"'
        )


def test_no_inline_widths_on_control_rows(body_html: str):
    """Redesign removes ``style="flex:1"`` / ``style="width:80px"``
    from the control rows -- they belong in the scoped CSS."""
    for block_re in (r'<div class="br-row">.*?</div>',):
        for m in re.finditer(block_re, body_html, flags=re.DOTALL):
            block = m.group(0)
            inline = re.findall(r'style="[^"]*(?:flex:|width:)', block)
            assert inline == [], (
                f"br-row has inline flex/width styles: {inline}. "
                "Move to scoped CSS."
            )


def test_url_tools_have_helpful_tooltips(body_html: str):
    """Each URL-tools button gets a ``title`` attribute -- keeps the
    UX self-documenting for users who don't know what Dump vs
    Fetch mean."""
    for kw in ("Extract readable text", "Full DOM dump",
               "Raw HTTP GET", "HTTP HEAD", "screenshot"):
        assert kw in body_html, f"missing tooltip snippet {kw!r}"
