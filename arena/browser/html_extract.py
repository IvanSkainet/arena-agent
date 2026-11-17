"""Bounded, non-recursive HTML extraction for the Python browser fallback."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

MAX_MARKUP = 8 * 1024 * 1024
MAX_DEPTH = 512
MAX_ELEMENTS = 100_000
_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_HIDDEN = frozenset(("script", "style", "template"))
_P_CLOSE = frozenset(("address article aside blockquote div dl fieldset footer form h1 h2 h3 h4 h5 h6 "
                      "header hgroup hr main menu nav ol p pre section table ul").split())
_IMPLIED = {
    "li": (("li",), ("ul", "ol", "menu")),
    "dt": (("dt", "dd"), ("dl",)), "dd": (("dt", "dd"), ("dl",)),
    "rt": (("rt", "rp"), ("ruby",)), "rp": (("rt", "rp"), ("ruby",)),
    "option": (("option",), ("select", "datalist", "optgroup")),
    "optgroup": (("optgroup",), ("select", "datalist")),
    "tr": (("tr",), ("table", "thead", "tbody", "tfoot")),
    "td": (("td", "th"), ("tr", "table")), "th": (("td", "th"), ("tr", "table")),
    "thead": (("thead", "tbody", "tfoot"), ("table",)),
    "tbody": (("thead", "tbody", "tfoot"), ("table",)),
    "tfoot": (("thead", "tbody", "tfoot"), ("table",)),
}


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
    """Extract bounded fields iteratively, without DOM/CSS evaluation."""

    def __init__(self, markup: str):
        """Parse bounded markup using an indexed, non-recursive context stack."""
        super().__init__(convert_charrefs=True)
        if len(markup) > MAX_MARKUP:
            raise ValueError("HTML exceeds extraction size limit")
        self._stack: list[_Context] = []
        self._open: dict[str, list[int]] = {}
        self._parts: list[str] = []
        self._titles: list[str] = []
        self._title_seen = False
        self._links: list[_Link] = []
        self._elements = 0
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._close_implied(tag)
        self._elements += 1
        if self._elements > MAX_ELEMENTS or len(self._stack) >= MAX_DEPTH:
            raise ValueError("HTML exceeds extraction structure limit")
        context = self._context(tag, attrs)
        if tag not in _VOID:
            self._open.setdefault(tag, []).append(len(self._stack))
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
        if context.hidden:
            return
        if context.tag == "a" and "href" in values:
            context.link = _Link(values["href"] or "", "result__a" in classes, context.result)
            self._links.append(context.link)

    def _last_open(self, tags: tuple[str, ...]) -> int:
        return max((self._open[tag][-1] for tag in tags if tag in self._open), default=-1)

    def _close_in_scope(self, targets: tuple[str, ...], barriers: tuple[str, ...]) -> None:
        index = self._last_open(targets)
        if index > max(self._last_open(barriers), self._last_open(("template",))):
            self._truncate(index)

    def _close_implied(self, tag: str) -> None:
        # These common optional end tags must not turn shallow valid HTML into
        # apparent deep nesting. Scope barriers preserve nested lists/tables.
        if tag in _P_CLOSE:
            self._close_in_scope(("p",), ("button", "table", "td", "th", "html"))
        if tag == "optgroup":
            self._close_in_scope(("option",), ("select", "datalist"))
        targets, barriers = _IMPLIED.get(tag, ((), ()))
        self._close_in_scope(targets, barriers)

    def _truncate(self, index: int) -> None:
        # Each pushed context is removed once: total work is amortized linear.
        while len(self._stack) > index:
            tag = self._stack.pop().tag
            positions = self._open[tag]
            positions.pop()
            if not positions:
                del self._open[tag]

    def handle_endtag(self, tag: str) -> None:
        positions = self._open.get(tag)
        if positions and positions[-1] >= self._last_open(("template",)):
            self._truncate(positions[-1])

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
