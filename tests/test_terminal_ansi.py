"""Tests for the ANSI SGR renderer in Terminal tab (v4.15.0).

Two layers:
1. Static guards on the JS bundle (same shape as every other
   dashboard-side test since v4.6.0).
2. **Real JS execution via node** -- the parser is small enough
   to load into a fresh V8, feed sample strings, and diff the
   HTML output. Guards against subtle bugs that a static check
   would miss (span nesting, malformed escapes, edge cases).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-02-terminal.html"
_JS_ANSI = _REPO / "dashboard" / "assets" / "05b-terminal-ansi.js"
_JS_TERM = _REPO / "dashboard" / "assets" / "05-terminal-v1-6-2-persistent-shell-like-se.js"
_CSS = _REPO / "dashboard" / "assets" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static guards
# ---------------------------------------------------------------------------
def test_ansi_module_present_and_exposes_expected_helpers():
    js = _read(_JS_ANSI)
    for name in ("__termAnsiToHtml", "__termAnsiStrip",
                 "__ansiStyleFromState", "__ansiApplyCodes",
                 "__ANSI_BASIC", "__ANSI_BRIGHT", "__ANSI_XTERM256"):
        assert name in js, f"ansi helper missing: {name}"


def test_terminal_uses_termwriteout_helper_not_bare_textcontent():
    """v4.15.0: every stdout/stderr write path must go through
    the ANSI-aware helper. Bare ``slot.out.textContent = ...``
    is only allowed inside the helper itself. Regression guard:
    a future edit that appends output directly would silently
    lose colour rendering."""
    js = _read(_JS_TERM)
    # Count call sites vs the one legitimate assignment inside
    # the helper body.
    calls = js.count("_termWriteOut(slot,")
    direct = js.count("slot.out.textContent =")
    assert calls >= 5, f"expected >=5 _termWriteOut call sites, got {calls}"
    # Exactly one direct assignment allowed -- the helper's own
    # fast path for ANSI-free strings.
    assert direct <= 1, (
        f"found {direct} bare slot.out.textContent = assignments; "
        "route them through _termWriteOut so ANSI escapes render"
    )


def test_termwriteout_helper_prefers_textcontent_when_no_escapes():
    """Zero-cost path for the common case: strings without
    ESC[ never hit innerHTML (which forces the whole SGR pipeline
    + a DOM parse). Guards against a rewrite that unconditionally
    uses innerHTML."""
    js = _read(_JS_TERM)
    # Find the _termWriteOut body.
    start = js.find("function _termWriteOut(")
    assert start != -1
    end = js.find("\nfunction ", start + 1)
    body = js[start:end] if end != -1 else js[start:start + 800]
    assert 'indexOf("\\x1b[")' in body, (
        "_termWriteOut must fast-path strings without ESC[ via "
        "textContent -- otherwise every ordinary command pays "
        "the SGR pipeline cost"
    )
    assert "textContent" in body
    assert "innerHTML" in body


def test_ansi_module_strips_non_sgr_csi_sequences():
    """Cursor moves, screen clears etc. must not appear as
    literals in the output pane (a shell like ``htop`` would
    otherwise dump a garbled stream of ``[?25l[H[2J...``).
    Regression guard on the strip regex."""
    js = _read(_JS_ANSI)
    # The stripping happens in __termAnsiToHtml when the final
    # byte of the CSI is not 'm'. Guard the branch existing.
    assert 'finalByte !== "m"' in js
    # And __termAnsiStrip drops anything ESC[...<final>.
    assert "__termAnsiStrip" in js
    # Regex is permissive enough to swallow DEC private modes
    # (ESC[?25l, ESC[<u, ...) not just SGR-shaped strings.
    assert "[\\x30-\\x3f]" in js and "[\\x40-\\x7e]" in js


def test_ansi_module_escapes_html_before_wrapping():
    """A stdout line like ``echo '<script>'`` in a green span
    must escape the angle brackets so no HTML gets injected.
    Guard the __ansiEsc helper is called for every emitted chunk."""
    js = _read(_JS_ANSI)
    assert "__ansiEsc(chunk)" in js
    # And the escape helper covers &, <, >, ".
    assert 'replace(/&/g, "&amp;")' in js
    assert 'replace(/</g, "&lt;")' in js


# ---------------------------------------------------------------------------
# CSS containment
# ---------------------------------------------------------------------------
def test_dashboard_css_untouched_by_ansi_work():
    css = _read(_CSS)
    for token in ("term-ansi", "ansi-span", "ANSI_"):
        assert token not in css, f"leaked into dashboard.css: {token}"


# ---------------------------------------------------------------------------
# Real JS execution via node -- integration tests
# ---------------------------------------------------------------------------
def _have_node() -> bool:
    return shutil.which("node") is not None


def _run_ansi_js(script_body: str) -> str:
    """Load 05b-terminal-ansi.js (which references ``esc`` as a
    module-global) into a fresh node process and run
    ``script_body``. Returns the trimmed stdout."""
    js = _read(_JS_ANSI)
    # The module calls esc(); provide a stub so __ansiEsc doesn't
    # short-circuit to its own fallback (which is what we test).
    prelude = (
        "// Stub esc() so __ansiEsc uses the same escape rules the\n"
        "// dashboard uses at runtime. Regression: if this stub\n"
        "// drifts from 00-core.js's esc(), tests catch it.\n"
        "function esc(s){return String(s).replace(/&/g,'&amp;')"
        ".replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');}\n"
    )
    proc = subprocess.run(
        ["node", "-e", prelude + js + "\n" + script_body],
        capture_output=True, text=True, timeout=10,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}\n"
            f"STDERR: {proc.stderr}\nSCRIPT: {script_body[:400]}"
        )
    return proc.stdout.strip()


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_plain_text_returns_escaped_no_spans():
    """Zero SGR codes -> the helper still escapes HTML but adds
    no <span> wrapper."""
    out = _run_ansi_js("process.stdout.write(__termAnsiToHtml('hello <world>'));")
    assert out == "hello &lt;world&gt;"


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_empty_and_null_return_empty_string():
    for inp in ("''", "null", "undefined"):
        out = _run_ansi_js(f"process.stdout.write(String(__termAnsiToHtml({inp})));")
        assert out == "", f"input {inp} produced {out!r}"


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_basic_foreground_colour_wraps_in_span():
    """ESC[31m foo ESC[0m -> red foo, no wrapper around trailing content."""
    src = "\\x1b[31mfoo\\x1b[0m bar"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert '<span style="color:#cc0000">foo</span>' in out
    # 'bar' must not be inside the span.
    assert " bar" in out
    assert "<span" not in out.split("</span>")[1]


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_bold_and_underline_compose():
    """ESC[1;4;33m -> bold + underline + yellow foreground."""
    src = "\\x1b[1;4;33mhi\\x1b[0m"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert "color:#c4a000" in out
    assert "font-weight:700" in out
    assert "text-decoration:underline" in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_256_colour_foreground():
    """ESC[38;5;196m -> a bright red from the xterm 256-cube."""
    src = "\\x1b[38;5;196mred\\x1b[0m"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    # 196 = 16 + 36*5 + 6*0 + 0 = 216 -> cube index (5,0,0) -> ff0000
    assert "color:#ff0000" in out
    assert ">red<" in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_truecolour_foreground():
    """ESC[38;2;r;g;b m -> hex-lowercase colour string."""
    src = "\\x1b[38;2;18;52;86mrgb\\x1b[0m"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert "color:#123456" in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_inverse_swaps_fg_and_bg():
    """ESC[7m -> visual inversion of the current fg/bg."""
    src = "\\x1b[31;44m\\x1b[7minv\\x1b[0m"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    # fg red (#cc0000) and bg blue (#3465a4) swap: colour becomes
    # blue-ish, background becomes red-ish.
    assert "color:#3465a4" in out
    assert "background:#cc0000" in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_non_sgr_csi_is_stripped_not_rendered():
    """A cursor-move (ESC[2J) or hide-cursor (ESC[?25l) is not
    SGR: must be silently dropped from the output. Otherwise a
    program like ``clear`` would leave ``[H[2J`` in the pane."""
    src = "\\x1b[2Jhello\\x1b[?25lworld"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert out == "helloworld", f"leftover CSI in output: {out!r}"


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_malformed_escape_does_not_throw():
    """A dangling ESC or an unterminated ESC[ must not crash the
    parser. Contract: emit the plain text after best-effort skip."""
    src = "before\\x1b[31after\\x1b[missingend"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    # Best-effort: 'before' is emitted as plain text; the
    # unterminated sequences pass through untouched (that's fine
    # for a scrollback pane).
    assert out.startswith("before")


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_reset_after_colour_closes_span_cleanly():
    """Sanity check on span balance: after a full colour-then-
    reset run the output must have equal counts of <span> and
    </span> (no leftover tags)."""
    src = "\\x1b[31mred\\x1b[0m plain \\x1b[32mgreen\\x1b[0m"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert out.count("<span") == out.count("</span>")
    assert out.count("<span") == 2


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_strip_removes_all_csi_leaves_visible_text():
    """__termAnsiStrip is what copy-to-clipboard should use; it
    must strip every CSI and leave the visible text intact."""
    src = "\\x1b[31mfoo\\x1b[0m\\x1b[2Jbar\\x1b[?25l"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiStrip('{src}'));")
    assert out == "foobar"


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_escape_helper_uses_esc_from_dashboard():
    """__ansiEsc must call the shared ``esc()`` if it exists.
    The prelude in _run_ansi_js supplies one that mirrors the
    real dashboard's escape rules -- so a payload with ``&``,
    ``<``, ``>``, ``"`` must all be escaped."""
    src = "\\x1b[31m<script>&\"end</script>\\x1b[0m"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert "&lt;script&gt;" in out
    assert "&amp;" in out
    assert "&quot;" in out
    # And no literal '<script>' anywhere -- if this fails we have
    # XSS.
    assert "<script>" not in out


@pytest.mark.skipif(not _have_node(), reason="node.js required")
def test_ansi_bright_foreground_range_90_to_97():
    """ESC[91m -> bright red (#ef2929, not the basic red #cc0000)."""
    src = "\\x1b[91mBR\\x1b[0m"
    out = _run_ansi_js(f"process.stdout.write(__termAnsiToHtml('{src}'));")
    assert "color:#ef2929" in out
    assert "color:#cc0000" not in out
