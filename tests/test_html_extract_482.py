"""Fixed HTML extraction contracts and structural bounds, without CSS engines."""
from __future__ import annotations

from unittest import TestCase

import pytest

from arena.browser import html_extract as html

CHECK = TestCase()


def test_text_entities_nested_links_and_hidden_content():
    page = html.ExtractedPage('<title> A &amp; B </title><p>Hello <b>world</b>!</p>'
                              '<script>secret-script</script><style>secret-style</style>'
                              '<template>secret-template</template><a href="/a?x=1&amp;y=2"> one <b>two</b></a>')
    CHECK.assertEqual(page.title, "A & B")
    CHECK.assertEqual(page.text(), "A & B\nHello\nworld\n!\none\ntwo")
    CHECK.assertEqual(page.links(), [{"text": "onetwo", "href": "/a?x=1&y=2"}])


def test_search_result_class_tokens_and_snippet_parent_isolation():
    page = html.ExtractedPage('<div class="other result"><a class="x result__a" href="/one">One</a>'
                              '<div class="result__snippet"> First <b>snippet</b> </div></div>'
                              '<div class="result"><a class="result__a" href="/two">Two</a>'
                              '<span class="result__snippet">Second</span></div>'
                              '<a class="result__a" href="/orphan">Orphan</a>'
                              '<a class="not-result__a" href="/ignore">Ignore</a>')
    CHECK.assertEqual(page.search_results(3), [
        {"title": "One", "url": "/one", "snippet": "First snippet"},
        {"title": "Two", "url": "/two", "snippet": "Second"},
        {"title": "Orphan", "url": "/orphan", "snippet": ""},
    ])
    CHECK.assertEqual(page.search_results(0), [])
    CHECK.assertEqual(len(page.search_results(1)), 1)


def test_void_elements_comments_and_mismatched_end_tags():
    page = html.ExtractedPage('<p>A<br>B<img src="x">C<!--hidden--><div>D</p>E</div>')
    CHECK.assertEqual(page.text(), "A\nB\nC\nD\nE")
    CHECK.assertEqual(page.title, "")
    CHECK.assertEqual(page.links(), [])


def test_no_recursive_walk_of_deep_document(monkeypatch):
    monkeypatch.setattr(html, "MAX_DEPTH", 4000)
    page = html.ExtractedPage('<div>' * 3000 + 'text' + '</div>' * 3000)
    CHECK.assertEqual(page.text(), "text")


@pytest.mark.parametrize("case", ["markup", "depth", "elements"])
def test_rejects_oversized_or_adversarial_structure(monkeypatch, case):
    monkeypatch.setattr(html, "MAX_MARKUP", 1000)
    monkeypatch.setattr(html, "MAX_DEPTH", 10)
    monkeypatch.setattr(html, "MAX_ELEMENTS", 10)
    markup = {"markup": "x" * 1001, "depth": '<div>' * 11,
              "elements": '<br>' * 11}[case]
    with pytest.raises(ValueError, match="extraction .* limit"):
        html.ExtractedPage(markup)


def test_link_output_limits_are_preserved():
    page = html.ExtractedPage('<a href="x">' + 'a' * 150 + '</a>' * 1 + '<a href="y">b</a>')
    CHECK.assertEqual(page.links(1), [{"href": "x", "text": 'a' * 120}])


def test_self_closing_tags_use_htmlparser_default_dispatch():
    page = html.ExtractedPage('<p>A<span/>B<br/>C</p><a href="x"/>outside')
    CHECK.assertEqual(page.text(), "A\nB\nC\noutside")
    CHECK.assertEqual(page.links(), [{"href": "x", "text": ""}])


def test_htmlparser_dispatches_text_to_the_extraction_callback(monkeypatch):
    original = html.ExtractedPage.handle_data
    seen = []

    def capture(parser, data):
        seen.append(data)
        original(parser, data)

    monkeypatch.setattr(html.ExtractedPage, "handle_data", capture)
    page = html.ExtractedPage('<b>text</b>&amp;tail')
    CHECK.assertEqual(seen, ["text", "&tail"])
    CHECK.assertEqual(page.text(), "text\n&tail")


def test_only_first_document_title_is_reported():
    CHECK.assertEqual(html.ExtractedPage('<title>first</title><title>second</title>').title, "first")
    CHECK.assertEqual(html.ExtractedPage('<title></title><title>second</title>').title, "")


@pytest.mark.parametrize("markup", [
    '<ul>' + '<li>x' * 600 + '</ul>',
    '<p>x' * 600,
    '<dl>' + '<dt>x<dd>y' * 600 + '</dl>',
    '<table>' + '<tr><td>x<td>y' * 600 + '</table>',
    '<select>' + '<option>x' * 600 + '</select>',
])
def test_omitted_optional_end_tags_do_not_look_like_deep_nesting(markup):
    page = html.ExtractedPage(markup)
    CHECK.assertGreaterEqual(page.text().count('x'), 600)


def test_nested_list_scope_preserves_outer_item():
    page = html.ExtractedPage('<ul><li>outer<ul><li>inner<li>inner2</ul><li>outer2</ul>')
    CHECK.assertEqual(page.text(), "outer\ninner\ninner2\nouter2")
    CHECK.assertEqual(page._stack, [])
    CHECK.assertEqual(page._open, {})


def test_unmatched_end_tags_do_not_walk_the_context_stack():
    page = html.ExtractedPage('<div>' * 500)
    reads = []

    class ObservedStack(list):
        def __getitem__(self, index):
            """Record indexing to expose a regression to full-stack scans."""
            reads.append(index)
            raise AssertionError("unmatched closing tag inspected the context stack")

    page._stack = ObservedStack(page._stack)
    page.feed('</unknown>' * 10000)
    CHECK.assertEqual(reads, [])
    CHECK.assertEqual(len(page._stack), 500)
    page.feed('</div>' * 500)
    CHECK.assertEqual(page._open, {})


def test_hidden_anchors_are_absent_from_links_and_search():
    page = html.ExtractedPage('<template><a class="result__a" href="hidden">bad</a></template>'
                              '<a class="result__a" href="visible">good</a>')
    CHECK.assertEqual(page.links(), [{"href": "visible", "text": "good"}])
    CHECK.assertEqual(page.search_results(3), [{"url": "visible", "title": "good", "snippet": ""}])
