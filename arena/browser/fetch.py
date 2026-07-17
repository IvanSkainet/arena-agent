"""Non-CDP browser/web fetch helpers."""
from __future__ import annotations

import html as _html
import re as _re
import urllib.parse as _up
import urllib.request
from collections.abc import Callable
from typing import Any

UrlValidator = Callable[[str], str | None]


def _request(url: str, *, version: str, method: str = "GET", timeout: int = 15) -> urllib.request.Request:
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", f"ArenaBridge/{version}")
    return req


def browser_search(query: str, n: int, *, version: str) -> dict[str, Any]:
    url = f"https://lite.duckduckgo.com/lite/?q={_up.quote_plus(query)}"
    req = _request(url, version=version, timeout=15)
    with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 -- SSRF-validated via arena.security_ssrf._validate_url before call
        content = resp.read().decode("utf-8", errors="replace")
    results = []
    link_pat = _re.compile(r'''<a[^>]+href="([^"]+)"[^>]*class='result-link'[^>]*>(.*?)</a>''', _re.DOTALL)
    snippet_pat = _re.compile(r'''class='result-snippet'[^>]*>(.*?)</td>''', _re.DOTALL)
    links = link_pat.findall(content)
    snippets = snippet_pat.findall(content)
    for i, (href, title) in enumerate(links[:n]):
        title_clean = _re.sub(r'<[^>]+>', '', title).strip()
        uddg = _re.search(r'uddg=([^&]+)', href)
        real_url = _up.unquote(uddg.group(1)) if uddg else href
        snippet = _re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
        results.append({"title": title_clean, "url": real_url, "snippet": snippet})
    return {"ok": True, "query": query, "count": len(results), "results": results}


def browser_read(url: str, *, version: str, validate_url: UrlValidator) -> dict[str, Any]:
    err = validate_url(url)
    if err:
        return {"ok": False, "error": err}
    req = _request(url, version=version, timeout=15)
    with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 -- SSRF-validated via arena.security_ssrf._validate_url before call
        content = resp.read().decode("utf-8", errors="replace")
    title = ""
    m = _re.search(r'<title[^>]*>(.*?)</title>', content, _re.IGNORECASE | _re.DOTALL)
    if m:
        title = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
    for tag in ["script", "style", "nav", "footer", "header", "aside", "noscript"]:
        content = _re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', content, flags=_re.DOTALL | _re.IGNORECASE)
    main = ""
    for sel in [r'<article[^>]*>(.*?)</article>', r'<main[^>]*>(.*?)</main>']:
        match = _re.search(sel, content, _re.DOTALL | _re.IGNORECASE)
        if match:
            main = match.group(1)
            break
    if not main:
        main = content
    text = _re.sub(r'<[^>]+>', ' ', main)
    text = _html.unescape(text)
    text = _re.sub(r'\s+', ' ', text).strip()
    if len(text) > 20000:
        text = text[:20000] + "\n...[truncated]"
    return {"ok": True, "title": title, "url": url, "text": text, "length": len(text)}


def browser_dump(url: str, *, version: str, validate_url: UrlValidator) -> dict[str, Any]:
    err = validate_url(url)
    if err:
        return {"ok": False, "error": err}
    req = _request(url, version=version, timeout=20)
    with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310 -- SSRF-validated via arena.security_ssrf._validate_url before call
        content = resp.read().decode("utf-8", errors="replace")
    title = ""
    m = _re.search(r'<title[^>]*>(.*?)</title>', content, _re.IGNORECASE | _re.DOTALL)
    if m:
        title = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
    links = []
    link_pat = _re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', _re.DOTALL | _re.IGNORECASE)
    for href, link_text in link_pat.findall(content):
        link_text_clean = _re.sub(r'<[^>]+>', '', link_text).strip()[:200]
        if href and not href.startswith(("javascript:", "#", "mailto:")):
            links.append({"text": link_text_clean, "url": href[:500]})
        if len(links) >= 500:
            break
    for tag in ["script", "style", "noscript"]:
        content = _re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', content, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r'<[^>]+>', ' ', content)
    text = _html.unescape(text)
    text = _re.sub(r'\s+', ' ', text).strip()
    if len(text) > 50000:
        text = text[:50000] + "\n...[truncated]"
    return {"ok": True, "title": title, "url": url, "text": text, "links": links[:200], "length": len(text), "link_count": len(links)}


def browser_fetch(url: str, *, version: str, validate_url: UrlValidator) -> dict[str, Any]:
    err = validate_url(url)
    if err:
        return {"ok": False, "error": err}
    req = _request(url, version=version, timeout=20)
    with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310 -- SSRF-validated via arena.security_ssrf._validate_url before call
        raw = resp.read()
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
    text: str | None = None
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", "replace")
    truncated = len(text) > 50000
    text = text[:50000]
    return {"ok": True, "url": url, "content_type": content_type, "length": len(raw), "text": text, "truncated": truncated}


def browser_head(url: str, *, version: str, validate_url: UrlValidator) -> dict[str, Any]:
    err = validate_url(url)
    if err:
        return {"ok": False, "error": err}
    req = _request(url, version=version, method="HEAD", timeout=15)
    with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 -- SSRF-validated via arena.security_ssrf._validate_url before call
        return {"ok": True, "url": url, "status_code": resp.status, "headers": dict(resp.headers)}
