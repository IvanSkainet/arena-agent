"""Tests for OSC sequence handling in the Terminal ANSI parser (v4.18.0).

v4.15.0 added a CSI-only SGR renderer; anything wrapped in an OSC
(``ESC ] Ps ; Pt ST``) still leaked through as literal text. Real
shells emit two OSCs frequently:

* ``OSC 8`` -- hyperlinks (``ls --hyperlink=always``, git diff, etc.)
* ``OSC 0/1/2`` -- window/tab title

v4.18.0 handles both: OSC 8 becomes a proper ``<a>`` wrap
(sanitised against dangerous schemes), titles are silently
dropped (Terminal tab has no title bar), everything else in the
OSC space (progress reports, iTerm2 shell integration, kitty
graphics) is silently stripped.

Static guards + real node.js integration tests -- same shape as
tests/test_terminal_ansi.py.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_JS_ANSI = _REPO / "dashboard" / "assets" / "05b-terminal-ansi.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static guards
# ---------------------------------------------------------------------------
def test_osc_helpers_present_in_module():
    js = _read(_JS_ANSI)
    for name in ("__oscPreprocess", "__oscSafeUrl", "_UNSAFE_SCHEMES"):
        assert name in js, f"OSC helper missing: {name}"


def test_unsafe_schemes_list_includes_javascript_and_data():
    """OSC 8 URLs are attacker-controlled bytes from stdout. The
    scheme reject-list is what prevents ``ESC]8;;javascript:alert(1)
    ESC\\ hi ESC]8;;ESC\\`` from becoming an active XSS on click."""
    js = _read(_JS_ANSI)
    for scheme in ("javascript:", "data:", "vbscript:", "file:"):
        assert scheme in js, f"reject-list missing scheme: {scheme}"


def test_sgr_body_extracted_to_inner_renderer():
    """v4.18.0 refactored the v4.15.0 SGR body into
    ``_ansiSgrHtml(src, state)`` so the OSC-preprocessing outer
    pass can drive it per text-run. Regression guard: if a future
    edit inlines it back the OSC state (open ``<a>``, colour
    carry-over across OSC 8 boundaries) will silently break."""
    js = _read(_JS_ANSI)
    assert "function _ansiSgrHtml(" in js
    # And the outer public function delegates through pieces.
    assert "__oscPreprocess(src)" in js
    assert "_ansiSgrHtml(p.data, state)" in js


def test_hyperlink_anchor_uses_safe_attributes():
    """OSC 8 anchors must open in a new tab (``target=_blank``)
    with the noreferrer noopener rel to prevent window.opener
    tab-jacking of the dashboard. Regression-guarded so a future
    edit that drops rel="noopener" fails immediately."""
    js = _read(_JS_ANSI)
    assert 'target="_blank"' in js
    assert "noopener" in js
    assert "noreferrer" in js


def test_strip_helper_drops_osc_before_csi():
    """__termAnsiStrip must strip both OSC and CSI so copy-to-
    clipboard produces the same visible text as __termAnsiToHtml
    (minus HTML wrappers)."""
    js = _read(_JS_ANSI)
    assert 'replace(/\\x1b\\][\\s\\S]*?(?:\\x07|\\x1b\\\\)/g, "")' in js


# ---------------------------------------------------------------------------
# Node.js integration
# ---------------------------------------------------------------------------
def _have_node() -> bool:
    return shutil.which("node") is not None


def _run_js(body: str) -> str:
    """Load the parser into a fresh node process (with the same
    ``esc()`` stub tests/test_terminal_ansi.py uses so the two
    suites see identical escape rules) and run ``body``."""
    js = _read(_JS_ANSI)
    prelude = (
        "function esc(s){return String(s).replace(/&/g,'&amp;')"
        ".replace(/</g,'&lt;').replace(/>/g,'&gt;')"
        ".replace(/\"/g,'&quot;');}\n"
    )
    proc = subprocess.run(
        ["node", "-e", prelude + js + "\n" + body],
        capture_output=True, text=True, timeout=10,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node exited {proc.returncode}\n"
                           f"STDERR: {proc.stderr}")
    return proc.stdout.strip()


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_hyperlink_wraps_text_in_anchor():
    """The canonical ``ls --hyperlink=always`` shape:
    ESC]8;;URL ESC\\ TEXT ESC]8;;ESC\\ -- becomes an <a> around TEXT."""
    src = "\\x1b]8;;https://example.com/foo\\x1b\\\\click me\\x1b]8;;\\x1b\\\\"
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert '<a href="https://example.com/foo"' in out
    assert 'target="_blank"' in out
    assert "noopener" in out
    assert ">click me</a>" in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_supports_bel_terminator():
    """Some shells terminate OSC with BEL (0x07) instead of
    ST (ESC\\). The parser must accept both."""
    src = "\\x1b]8;;https://example.com/bel\\x07here\\x1b]8;;\\x07"
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert '<a href="https://example.com/bel"' in out
    assert ">here</a>" in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_javascript_scheme_stripped():
    """``ESC]8;;javascript:alert(1)ESC\\ click ESC]8;;ESC\\`` --
    the anchor must NOT render (unsafe scheme) but the visible
    text still does."""
    src = "\\x1b]8;;javascript:alert(1)\\x1b\\\\click\\x1b]8;;\\x1b\\\\"
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert "javascript:" not in out
    assert "<a href=" not in out
    assert "click" in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_data_scheme_stripped():
    src = "\\x1b]8;;data:text/html;base64,PHNjcmlwdD4=\\x1b\\\\x\\x1b]8;;\\x1b\\\\"
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert "data:" not in out
    assert "<a href=" not in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_vbscript_scheme_stripped():
    src = "\\x1b]8;;VBSCRIPT:msgbox\\x1b\\\\x\\x1b]8;;\\x1b\\\\"
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert "vbscript" not in out.lower()
    assert "<a href=" not in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_url_with_html_metachars_escaped_in_href():
    """A URL like ``https://x.com/?q=<script>`` (technically
    invalid but shells can print anything). Guard: even if we
    accepted it, the < > escape prevents attribute-context XSS.
    Our stricter rule rejects it entirely due to control-char
    filter; verify that path."""
    src = "\\x1b]8;;https://x.com/?q=<script>\\x1b\\\\x\\x1b]8;;\\x1b\\\\"
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    # The URL fails the safety check -> no <a> emitted -> literal x.
    assert "<a href=" not in out
    assert "<script>" not in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_0_1_2_title_silently_dropped():
    """OSC 0/1/2 set the window/tab title. We have no title bar;
    they must be stripped without a trace in the output text."""
    for ps in ("0", "1", "2"):
        src = f"\\x1b]{ps};my terminal title\\x1b\\\\visible-text"
        out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
        assert out == "visible-text", (
            f"OSC {ps} leaked: {out!r}"
        )


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_unknown_ps_silently_dropped():
    """Progress reports (OSC 9), iTerm2 (OSC 1337), Kitty images
    (OSC 771) etc. -- everything unknown gets dropped so a shell
    that goes ham with escape sequences doesn't dump garbage."""
    for ps in ("9", "1337", "771", "133"):
        src = f"\\x1b]{ps};payload data here\\x1b\\\\hello"
        out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
        assert out == "hello", f"OSC {ps} leaked: {out!r}"


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_colour_carries_across_hyperlink_boundary():
    """SGR state must survive the OSC-split so a colour opened
    before the hyperlink continues after it closes. Real shells
    do this constantly (git diff colour continues across a
    filename hyperlink)."""
    src = ("\\x1b[31mred-before "
           "\\x1b]8;;https://ex.com/\\x1b\\\\link\\x1b]8;;\\x1b\\\\"
           " red-after\\x1b[0m")
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    # 'red-before' and 'red-after' both wrapped in the red span.
    assert out.count('color:#cc0000') >= 2
    # The <a> is present and its text has the colour applied inside.
    assert '<a href="https://ex.com/"' in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_strip_helper_drops_hyperlinks_and_titles():
    """__termAnsiStrip -> pure visible text (for copy-to-clipboard).
    No <a>, no href, no OSC bytes."""
    src = ("prefix "
           "\\x1b]8;;https://ex.com/\\x1b\\\\link\\x1b]8;;\\x1b\\\\"
           " \\x1b]0;title\\x1b\\\\ suffix")
    out = _run_js(f"process.stdout.write(__termAnsiStrip('{src}'));")
    assert out == "prefix link  suffix"


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_close_without_open_is_safe():
    """A stray OSC 8 close (empty URL) with no preceding open must
    not emit ``</a>`` -- otherwise a well-behaved parser would
    render an unbalanced tag. Guard the ``openHref`` tracking."""
    src = "hello \\x1b]8;;\\x1b\\\\ world"
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert "</a>" not in out
    assert "hello" in out and "world" in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_unclosed_open_closes_at_end_of_input():
    """A missing OSC 8 close at end of input must still balance
    the anchor so the DOM doesn't inherit an open <a> that would
    make every subsequent element clickable."""
    src = "before \\x1b]8;;https://ex.com/\\x1b\\\\clicky"
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert out.count("<a href") == 1
    assert out.count("</a>") == 1
    assert out.endswith("</a>")


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_8_url_with_id_params_preserved():
    """OSC 8 payload can include per-link params (``id=foo``) before
    the URL: ``ESC]8;id=foo;URL ESC\\``. We must split correctly
    and keep the URL, not the whole ``id=foo;URL`` string."""
    src = "\\x1b]8;id=xyz;https://example.com/id\\x1b\\\\hey\\x1b]8;;\\x1b\\\\"
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert '<a href="https://example.com/id"' in out
    assert "id=xyz" not in out    # params dropped, not in href


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_osc_and_csi_compose_normally():
    """Combined real-world payload: a coloured, hyperlinked chunk
    of text. Both parsers cooperating means the anchor wraps
    coloured text without duplicated span tags."""
    src = ("\\x1b[32m"
           "\\x1b]8;;https://example.com/\\x1b\\\\"
           "green-link"
           "\\x1b]8;;\\x1b\\\\"
           "\\x1b[0m")
    out = _run_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert '<a href="https://example.com/"' in out
    assert "color:#4e9a06" in out
    assert ">green-link<" in out
    # Balance sanity.
    assert out.count("<span") == out.count("</span>")
    assert out.count("<a ") == out.count("</a>")
