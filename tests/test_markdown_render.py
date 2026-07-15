"""Tests for the minimal Markdown -> HTML renderer (v3.86.4)."""
from __future__ import annotations

import pytest


def test_headings():
    from arena.gui.markdown_render import render
    assert "<h1>Hello</h1>" in render("# Hello")
    assert "<h2>Sub</h2>" in render("## Sub")
    assert "<h3>Third</h3>" in render("### Third")


def test_paragraphs_and_bold_italic_code():
    from arena.gui.markdown_render import render
    md = "This is **bold** and *italic* and `code`."
    out = render(md)
    assert "<strong>bold</strong>" in out
    assert "<em>italic</em>" in out
    assert "<code>code</code>" in out
    assert "<p>" in out


def test_links_render_safely():
    from arena.gui.markdown_render import render
    out = render("Visit [GitHub](https://github.com/x/y).")
    assert 'href="https://github.com/x/y"' in out
    assert 'target="_blank"' in out
    assert 'rel="noopener"' in out


def test_links_reject_javascript_urls():
    from arena.gui.markdown_render import render
    out = render("[click](javascript:alert(1))")
    assert "javascript:" not in out
    assert 'href="#"' in out


def test_unordered_list():
    from arena.gui.markdown_render import render
    out = render("- one\n- two\n- three")
    assert "<ul>" in out
    assert "<li>one</li>" in out
    assert "<li>three</li>" in out


def test_ordered_list():
    from arena.gui.markdown_render import render
    out = render("1. first\n2. second")
    assert "<ol>" in out
    assert "<li>first</li>" in out


def test_fenced_code_block_escapes_html():
    from arena.gui.markdown_render import render
    md = "```\n<script>bad</script>\n```"
    out = render(md)
    assert "<pre><code>" in out
    assert "&lt;script&gt;" in out
    # Raw <script> must NOT appear in the output.
    assert "<script>" not in out


def test_blockquote():
    from arena.gui.markdown_render import render
    out = render("> A quote\n> continued")
    assert "<blockquote>" in out
    assert "</blockquote>" in out


def test_horizontal_rule():
    from arena.gui.markdown_render import render
    assert "<hr>" in render("---")


def test_html_escape_in_regular_paragraph():
    from arena.gui.markdown_render import render
    out = render("Danger: <script>x</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_wrap_page_produces_full_html_document():
    from arena.gui.markdown_render import render, wrap_page
    body = render("# hi")
    page = wrap_page("test.md", body)
    assert page.startswith("<!DOCTYPE html>")
    assert "<title>test.md</title>" in page
    assert body in page
    # Dark theme colors present.
    assert "--bg" in page
    # Back link back to the Dashboard.
    assert "Back to Dashboard" in page


def test_wrap_page_escapes_title():
    from arena.gui.markdown_render import wrap_page
    page = wrap_page("<script>alert(1)</script>", "<p>x</p>")
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
