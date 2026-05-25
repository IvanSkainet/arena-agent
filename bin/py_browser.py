#!/usr/bin/python3
"""Pure-Python browser fallback.

Используется когда Chromium/Firefox упали (p11-kit и т.п. issues).
Команды:
  py_browser.py fetch URL              -> raw HTML
  py_browser.py read URL               -> readability-cleaned text + title
  py_browser.py dump URL [--save F]    -> JSON {url,title,text,links[]}
  py_browser.py search QUERY [--n 5]   -> DuckDuckGo HTML результаты JSON
  py_browser.py head URL               -> заголовки HTTP

Никаких внешних бинарей — только stdlib + requests + bs4 + readability-lxml.
Хорошо подходит как failover в нашем "ИБП" пути.
"""
from __future__ import annotations
import argparse, json, sys, html
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) ArenaAgent/0.5 PyBrowser/1.0"
H  = {"User-Agent": UA, "Accept-Language": "en,ru;q=0.8"}

def _get(url: str, timeout: int = 20) -> requests.Response:
    return requests.get(url, headers=H, timeout=timeout, allow_redirects=True)

def cmd_fetch(url: str) -> int:
    r = _get(url); sys.stdout.write(r.text); return 0

def cmd_head(url: str) -> int:
    r = requests.head(url, headers=H, timeout=15, allow_redirects=True)
    print(json.dumps({"status": r.status_code, "url": r.url,
                      "headers": dict(r.headers)}, ensure_ascii=False, indent=2))
    return 0

def cmd_read(url: str) -> int:
    from readability import Document
    r = _get(url); doc = Document(r.text)
    soup = BeautifulSoup(doc.summary(), "lxml")
    print(json.dumps({"url": r.url, "title": doc.short_title(),
                      "text": soup.get_text("\n", strip=True)},
                     ensure_ascii=False, indent=2))
    return 0

def cmd_dump(url: str, save: str|None) -> int:
    r = _get(url); s = BeautifulSoup(r.text, "lxml")
    title = (s.title.string.strip() if s.title and s.title.string else "")
    text = s.get_text("\n", strip=True)
    links = [{"text": a.get_text(strip=True)[:120], "href": a.get("href","")}
             for a in s.find_all("a", href=True)][:200]
    out = {"url": r.url, "status": r.status_code, "title": title,
           "text": text[:50000], "links": links}
    data = json.dumps(out, ensure_ascii=False, indent=2)
    if save:
        with open(save, "w", encoding="utf-8") as f: f.write(data)
        print(f"saved: {save} ({len(data)} bytes)")
    else:
        print(data)
    return 0

def cmd_search(q: str, n: int) -> int:
    # DuckDuckGo HTML endpoint — без JS, дружелюбен к scraper'ам
    r = requests.post("https://html.duckduckgo.com/html/",
                      data={"q": q}, headers=H, timeout=20)
    s = BeautifulSoup(r.text, "lxml")
    res = []
    for a in s.select("a.result__a")[:n]:
        href = a.get("href","")
        title = a.get_text(strip=True)
        snippet_el = a.find_parent("div", class_="result").select_one(".result__snippet") if a.find_parent("div", class_="result") else None
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        res.append({"title": title, "url": href, "snippet": snippet[:300]})
    print(json.dumps({"query": q, "results": res}, ensure_ascii=False, indent=2))
    return 0

def main() -> int:
    p = argparse.ArgumentParser(prog="py_browser", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("fetch","read","head"):
        sp = sub.add_parser(name); sp.add_argument("url")
    sp = sub.add_parser("dump"); sp.add_argument("url"); sp.add_argument("--save")
    sp = sub.add_parser("search"); sp.add_argument("query"); sp.add_argument("--n", type=int, default=5)
    args = p.parse_args()
    try:
        if args.cmd == "fetch":  return cmd_fetch(args.url)
        if args.cmd == "head":   return cmd_head(args.url)
        if args.cmd == "read":   return cmd_read(args.url)
        if args.cmd == "dump":   return cmd_dump(args.url, args.save)
        if args.cmd == "search": return cmd_search(args.query, args.n)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "cmd": args.cmd}), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
