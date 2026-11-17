"""Bounded, non-recursive HTML extraction for the Python browser fallback."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

MAX_MARKUP = 8 * 1024 * 1024
MAX_DEPTH = 512
MAX_ELEMENTS = 100_000
_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_HIDDEN = frozenset(("script", "style", "template"))


def _text(parts: list[str], separator: str = "") -> str:
    return separator.join(part.strip() for part in parts if part.strip())


@dataclass
class _Result:
    snippet: list[str] = field(default_factory=list)


@dataclass
class _Link:
    href: str
    search: bool
    result: _Result | None
    parts: list[str] = field(default_factory=list)


@dataclass
class _Context:
    tag: str = ""
    link: _Link | None = None
    result: _Result | None = None
    snippet: bool = False
    hidden: bool = False
    title: bool = False


class ExtractedPage(HTMLParser):
    """Extract fixed fields, never compile or evaluate CSS selectors.

    Deliberately not a browser DOM or a replacement for arbitrary BeautifulSoup
    APIs. Input, element count and stack depth are bounded; no recursive walks.
    """

    def __init__(self, markup: str):
        super().__init__(convert_charrefs=True)
        if len(markup) > MAX_MARKUP:
            raise ValueError("HTML exceeds extraction size limit")
        self._stack: list[_Context] = []
        self._parts: list[str] = []
        self._titles: list[str] = []
        self._title_seen = False
        self._links: list[_Link] = []
        self._elements = 0
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._elements += 1
        if self._elements > MAX_ELEMENTS or len(self._stack) >= MAX_DEPTH:
            raise ValueError("HTML exceeds extraction structure limit")
        context = self._context(tag, attrs)
        if tag not in _VOID:
            self._stack.append(context)

    def _context(self, tag: str, attrs: list[tuple[str, str | None]]) -> _Context:
        parent = self._stack[-1] if self._stack else _Context()
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        result = _Result() if tag == "div" and "result" in classes else parent.result
        context = _Context(tag=tag, link=parent.link, result=result,
                           snippet=parent.snippet or "result__snippet" in classes,
                           hidden=parent.hidden or tag in _HIDDEN,
                           title=parent.title)
        if tag == "title" and not self._title_seen:
            context.title = True
            self._title_seen = True
        self._attach_link(context, values, classes)
        return context

    def _attach_link(self, context: _Context, values: dict[str, str | None], classes: list[str]) -> None:
        if context.tag == "a" and "href" in values:
            context.link = _Link(values["href"] or "", "result__a" in classes, context.result)
            self._links.append(context.link)

    def handle_endtag(self, tag: str) -> None:
        # Tolerate missing/mismatched end tags without recursion. Work per
        # token is bounded by MAX_DEPTH even for hostile malformed input.
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        context = self._stack[-1] if self._stack else _Context()
        if context.hidden:
            return
        self._parts.append(data)
        if context.title:
            self._titles.append(data)
        if context.link is not None:
            context.link.parts.append(data)
        if context.snippet and context.result is not None:
            context.result.snippet.append(data)

    @property
    def title(self) -> str:
        return "".join(self._titles).strip()

    def text(self, separator: str = "\n") -> str:
        return _text(self._parts, separator)

    def links(self, limit: int = 200) -> list[dict[str, str]]:
        return [{"text": _text(link.parts)[:120], "href": link.href}
                for link in self._links[:limit]]

    def search_results(self, limit: int) -> list[dict[str, str]]:
        links = [link for link in self._links if link.search]
        return [{"title": _text(link.parts), "url": link.href,
                 "snippet": _text(link.result.snippet, " ")[:300] if link.result else ""}
                for link in links[:limit]]
