"""Tests for DuckDuckGo search parser (arena/browser/fetch.py).

Tests the HTML parsing logic of browser_search without making real network
requests, by monkeypatching urllib.request.urlopen to return canned HTML
that mimics lite.duckduckgo.com/lite/ response format.
"""
import sys
import io
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.browser.fetch import browser_search  # noqa: E402


# Sample HTML mimicking lite.duckduckgo.com/lite/ response structure
# Based on real DDG lite HTML: <a href="..." class='result-link'>title</a>
# and <td class='result-snippet'>snippet text</td>
_SAMPLE_DDG_HTML = b"""<html><body>
<table>
<tr><td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F&rut=abc" class='result-link'>Welcome to Python.org</a>
</td></tr>
<tr><td class='result-snippet'>
Python is a versatile and easy-to-learn programming language.
</td></tr>

<tr><td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.w3schools.com%2Fpython%2F&rut=def" class='result-link'>Python Tutorial - W3Schools</a>
</td></tr>
<tr><td class='result-snippet'>
Python is a popular programming language. Python can be used on a server.
</td></tr>

<tr><td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FPython_(programming_language)&rut=ghi" class='result-link'>Python (programming language) - Wikipedia</a>
</td></tr>
<tr><td class='result-snippet'>
Python supports multiple programming paradigms.
</td></tr>
</table>
</body></html>"""

# HTML with no results
_EMPTY_DDG_HTML = b"""<html><body>
<div class="header">DuckDuckGo</div>
<form action="/lite/" method="post">
<input class='query' type="text" name="q" value="zzznonexistent">
</form>
</body></html>"""

# HTML with HTML tags inside titles and snippets (bold tags from DDG)
_BOLD_DDG_HTML = b"""<html><body>
<tr><td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F&rut=x" class='result-link'><b>Example</b> Domain</a>
</td></tr>
<tr><td class='result-snippet'>
This domain is for use in <b>documentation</b> examples without needing permission.
</td></tr>
</body></html>"""


class _MockResponse:
    """Mock urllib response object."""
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_browser_search_parses_results():
    """browser_search correctly parses DDG lite HTML into results list."""
    with patch("urllib.request.urlopen", return_value=_MockResponse(_SAMPLE_DDG_HTML)):
        result = browser_search("python", 3, version="test")
    assert result["ok"] is True
    assert result["query"] == "python"
    assert result["count"] == 3
    assert len(result["results"]) == 3
    # Check first result
    assert result["results"][0]["title"] == "Welcome to Python.org"
    assert result["results"][0]["url"] == "https://www.python.org/"
    assert "versatile" in result["results"][0]["snippet"]
    # Check second result
    assert result["results"][1]["title"] == "Python Tutorial - W3Schools"
    assert result["results"][1]["url"] == "https://www.w3schools.com/python/"
    # Check third result
    assert "Wikipedia" in result["results"][2]["title"]


def test_browser_search_limits_results():
    """browser_search respects the n parameter (max results)."""
    with patch("urllib.request.urlopen", return_value=_MockResponse(_SAMPLE_DDG_HTML)):
        result = browser_search("python", 2, version="test")
    assert result["count"] == 2
    assert len(result["results"]) == 2


def test_browser_search_empty_results():
    """browser_search returns empty list when DDG has no results."""
    with patch("urllib.request.urlopen", return_value=_MockResponse(_EMPTY_DDG_HTML)):
        result = browser_search("zzznonexistent", 5, version="test")
    assert result["ok"] is True
    assert result["count"] == 0
    assert result["results"] == []


def test_browser_search_strips_html_tags_from_title():
    """browser_search strips <b> tags from titles."""
    with patch("urllib.request.urlopen", return_value=_MockResponse(_BOLD_DDG_HTML)):
        result = browser_search("example", 1, version="test")
    assert result["count"] == 1
    assert result["results"][0]["title"] == "Example Domain"
    assert "<b>" not in result["results"][0]["title"]


def test_browser_search_strips_html_tags_from_snippet():
    """browser_search strips <b> tags from snippets."""
    with patch("urllib.request.urlopen", return_value=_MockResponse(_BOLD_DDG_HTML)):
        result = browser_search("example", 1, version="test")
    assert "<b>" not in result["results"][0]["snippet"]
    assert "documentation" in result["results"][0]["snippet"]


def test_browser_search_url_decoding():
    """browser_search correctly URL-decodes the uddg parameter to get real URL."""
    with patch("urllib.request.urlopen", return_value=_MockResponse(_SAMPLE_DDG_HTML)):
        result = browser_search("python", 3, version="test")
    # The uddg parameter contains URL-encoded real URL
    assert result["results"][0]["url"] == "https://www.python.org/"
    assert result["results"][2]["url"] == "https://en.wikipedia.org/wiki/Python_(programming_language)"


def test_browser_search_query_in_response():
    """browser_search includes the original query in the response."""
    with patch("urllib.request.urlopen", return_value=_MockResponse(_SAMPLE_DDG_HTML)):
        result = browser_search("python programming", 1, version="test")
    assert result["query"] == "python programming"


def test_browser_search_n_zero():
    """browser_search with n=0 returns 0 results."""
    with patch("urllib.request.urlopen", return_value=_MockResponse(_SAMPLE_DDG_HTML)):
        result = browser_search("python", 0, version="test")
    assert result["count"] == 0
    assert result["results"] == []


def test_browser_search_n_larger_than_available():
    """browser_search with n larger than available results returns all available."""
    with patch("urllib.request.urlopen", return_value=_MockResponse(_SAMPLE_DDG_HTML)):
        result = browser_search("python", 10, version="test")
    assert result["count"] == 3  # only 3 in the sample HTML
    assert len(result["results"]) == 3


def test_browser_search_sets_user_agent():
    """browser_search sets the User-Agent header on the request."""
    captured_req = []
    def mock_urlopen(req, timeout=None):
        captured_req.append(req)
        return _MockResponse(_SAMPLE_DDG_HTML)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        browser_search("test", 1, version="3.2.1")

    assert len(captured_req) == 1
    ua = captured_req[0].headers.get("User-agent", "")
    assert "ArenaBridge/3.2.1" in ua
