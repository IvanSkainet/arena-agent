"""Static structural checks for the Terminal tab redesign (v4.26.0).

The Terminal tab was one of only two tabs that already had a
scoped ``<style>`` block (kill button + stream dot from the
v4.13.0/v4.15.0 streaming work). This redesign brings the rest
of the tab up to the same visual language as Audit / Overview /
Proposals: uniform toolbar, meta line, consolidated palette.

Every id the existing loaders reach for must survive:
  * 05-terminal-*.js reads termCmd, termTimeout, termStream,
    termSession, termHistory, termDuration.
  * 05b-terminal-ansi.js reads termSession (shared with above).
  * 21-slash-commands.js reads termSuggest and termCmd.

Missing any of these silently breaks the tab. This test file is
the guarantee that a future refactor cannot regress that.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-02-terminal.html"


@pytest.fixture(scope="module")
def body_html() -> str:
    return _BODY.read_text(encoding="utf-8")


PRESERVED_IDS = [
    "termCmd", "termSuggest", "termTimeout", "termStream",
    "termSession", "termHistory", "termDuration",
]


@pytest.mark.parametrize("id_", PRESERVED_IDS)
def test_preserved_id_present(body_html: str, id_: str):
    assert f'id="{id_}"' in body_html, (
        f"Terminal redesign removed #{id_} -- would silently break "
        f"05-terminal-*.js / 05b-terminal-ansi.js / 21-slash-commands.js"
    )


def test_new_meta_line_present(body_html: str):
    """Redesign adds a #termMeta line under the toolbar (same
    pattern Audit / Overview / Proposals use)."""
    assert 'id="termMeta"' in body_html


def test_tab_wrapper_and_h1_present(body_html: str):
    assert 'id="tab-terminal"' in body_html
    assert '<h1>Terminal</h1>' in body_html


def test_stream_toggle_still_wired(body_html: str):
    """The v4.13.0 stream-mode checkbox stays; the redesign must
    not drop the ``onclick="runCommand()"`` binding either."""
    assert 'id="termStream"' in body_html
    assert 'runCommand()' in body_html
    assert 'clearTerminal()' in body_html
    assert 'copyTermOutput()' in body_html


def test_timeout_selector_default_stays_30_seconds(body_html: str):
    """A 30s default was the pre-redesign norm; keep it so muscle
    memory holds."""
    m = re.search(r'<option value="30"\s+selected>', body_html)
    assert m, "30s must remain the selected default"


# ---------------------------------------------------------------------------
# scoped CSS discipline
# ---------------------------------------------------------------------------
def test_every_style_selector_scoped_to_tab_terminal(body_html: str):
    style_blocks = re.findall(r"<style>(.*?)</style>", body_html,
                              flags=re.DOTALL)
    assert style_blocks

    def strip_comments(css: str) -> str:
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    def strip_at_rules(css: str) -> str:
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
            for selector in m.group(1).split(","):
                selector = selector.strip()
                if not selector or selector.startswith("@"):
                    continue
                assert selector.startswith("#tab-terminal"), (
                    f"Unscoped selector in Terminal <style>: {selector!r}"
                )


def test_palette_vars_scoped_inside_tab(body_html: str):
    assert "#tab-terminal{" in body_html or "#tab-terminal {" in body_html
    for var in ("--tm-tint-blue", "--tm-tint-green", "--tm-tint-red",
                "--term-kill-hover"):
        assert var in body_html, f"missing scoped palette var {var}"


def test_no_inline_widths_on_toolbar(body_html: str):
    """The redesign moves width overrides into scoped CSS classes
    (``.tm-toolbar select`` etc). Guard against a future edit that
    re-adds inline width= attributes to toolbar controls."""
    # Grab only the toolbar block for locality.
    m = re.search(r'<div class="tm-toolbar">.*?</div>', body_html,
                  flags=re.DOTALL)
    assert m, "tm-toolbar block missing"
    block = m.group(0)
    inline = re.findall(r'style="[^"]*width:', block)
    assert inline == [], (
        f"tm-toolbar contains inline width= styles: {inline}. "
        "Move them into the scoped CSS block."
    )


def test_slash_hints_still_present(body_html: str):
    """The hint strip advertising /shot /search /read etc. is a
    usability affordance; a redesign that drops it would leave
    users guessing. Keep it."""
    hint = body_html[body_html.find('class="tm-hint"'):
                     body_html.find('class="tm-hint"') + 500]
    for cmd in ("/shot", "/search", "/read", "/dump", "/status", "/doctor"):
        assert cmd in hint, f"slash hint missing {cmd}"


def test_stream_dot_and_kill_button_classes_intact(body_html: str):
    """v4.13.0/v4.15.0 gave the streaming loader these classes; the
    redesign must not rename or drop them."""
    assert ".term-kill-btn" in body_html
    assert ".term-stream-dot" in body_html
    # Kill hover retains its scoped hex-variable indirection so
    # test_no_hardcoded_theme_colors doesn't fire.
    assert "--term-kill-hover" in body_html


def test_history_section_kept(body_html: str):
    """The <details><summary>Recent commands</summary> block is a
    small but heavily-used affordance."""
    assert 'class="tm-history"' in body_html
    assert 'Recent commands' in body_html
    assert 'id="termHistory"' in body_html
