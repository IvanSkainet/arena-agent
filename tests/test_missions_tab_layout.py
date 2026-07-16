"""Static structural checks for the Missions tab redesign."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-05-missions.html"
_JS = _REPO / "dashboard" / "assets" / "08b-missions-toolbar.js"


@pytest.fixture(scope="module")
def body_html() -> str:
    return _BODY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js_text() -> str:
    return _JS.read_text(encoding="utf-8")


PRESERVED_IDS = ["missionsTable"]
NEW_TOOLBAR_IDS = ["missionsAuto", "missionsInterval",
                   "missionsRefreshDot", "missionsMeta"]


@pytest.mark.parametrize("id_", PRESERVED_IDS + NEW_TOOLBAR_IDS)
def test_id_present(body_html: str, id_: str):
    assert f'id="{id_}"' in body_html


def test_tab_wrapper(body_html: str):
    assert 'id="tab-missions"' in body_html
    assert '<h1>Missions</h1>' in body_html


def test_reload_handler_wired(body_html: str):
    assert 'onclick="loadMissions()"' in body_html


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
                assert sel.startswith("#tab-missions"), (
                    f"Unscoped selector: {sel!r}"
                )


def test_palette_scoped(body_html: str):
    assert "#tab-missions{" in body_html or "#tab-missions {" in body_html
    for var in ("--ms-tint-green", "--ms-tint-blue"):
        assert var in body_html


def test_toolbar_interval_options(body_html: str):
    for v in ('value="15"', 'value="30"', 'value="60"', 'value="300"'):
        assert v in body_html


def test_columns_have_width_classes(body_html: str):
    for cls in ("col-type", "col-size", "col-modified"):
        assert cls in body_html


# ------ JS toolbar module hygiene ------
def test_js_is_iife(js_text: str):
    lines = [l.strip() for l in js_text.splitlines()
             if l.strip() and not l.strip().startswith("//")]
    assert lines[0].startswith("(function")


def test_js_wraps_loadMissions(js_text: str):
    assert "window.loadMissions" in js_text
    assert "_originalLoad" in js_text


def test_js_no_hardcoded_setInterval_delay(js_text: str):
    matches = re.findall(r"setInterval\([^,]+,\s*(\d+)\)", js_text)
    assert matches == [], f"hardcoded delays: {matches}"


def test_js_exposes_diagnostic_namespace(js_text: str):
    assert "__missionsToolbar" in js_text
    assert "enumerable: false" in js_text
