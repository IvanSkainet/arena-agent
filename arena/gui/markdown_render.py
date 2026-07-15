"""Minimal Markdown → HTML renderer for `/gui/docs/*.md` (v3.86.4).

Deliberately small (~150 lines, no dependencies) so a bridge without
the `markdown` PyPI package still renders documentation correctly in
the Dashboard. Supports the subset we actually use in our own docs:

  * Headings `#`, `##`, `###`
  * Bold `**x**`, italic `*x*`, inline code `` `x` ``
  * Links `[text](url)`
  * Unordered lists (`- ` or `* `)
  * Ordered lists (`1. `)
  * Fenced code blocks ```` ``` ````
  * Blockquotes `> `
  * Horizontal rules `---`
  * Paragraphs

Not supported (would need a real parser -- worth pulling in a
dependency the day we need any of these):

  * Tables, footnotes, HTML passthrough, inline HTML sanitising,
    nested lists deeper than one level, image `![alt](url)`.

Security posture: everything is HTML-escaped before Markdown syntax
is applied. The only HTML we generate is our own tags. `href` values
are lightly sanitised (only http:/https:/mailto:/relative allowed)
so a malicious CHANGELOG.md can't inject `javascript:` URLs.
"""
from __future__ import annotations

import html
import re


_LINK_SAFE = re.compile(r"^(https?://|mailto:|/|#|\.)", re.IGNORECASE)


def _safe_href(url: str) -> str:
    """Return `url` if it starts with an allowed prefix, else '#'."""
    if _LINK_SAFE.match(url or ""):
        return html.escape(url, quote=True)
    return "#"


def _render_inline(text: str) -> str:
    """Apply inline Markdown to an already HTML-escaped string.
    Order matters: code first so backtick spans don't get bold-italic
    processed inside them."""
    # Inline code `x`
    def _code(m: re.Match) -> str:
        return f'<code>{m.group(1)}</code>'
    text = re.sub(r"`([^`\n]+)`", _code, text)

    # Links [text](url)
    def _link(m: re.Match) -> str:
        label = m.group(1)
        href = _safe_href(m.group(2))
        return f'<a href="{href}" target="_blank" rel="noopener">{label}</a>'
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, text)

    # Bold **x**
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", text)

    # Italic *x* (single asterisk, not part of ** or middle-of-word)
    text = re.sub(r"(^|[\s(])\*([^*\n]+)\*(?=[\s.,;:!?)]|$)",
                  r"\1<em>\2</em>", text)

    return text


def render(md: str) -> str:
    """Render `md` (a Markdown string) as an HTML fragment ready to
    drop into a `<div>`.

    Not a fragment of a full document -- the caller wraps this in
    `<html><body>` with the CSS they want."""
    lines = md.splitlines()
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    in_list = False
    list_tag = "ul"
    in_blockquote = False
    para_buf: list[str] = []

    def _flush_para():
        if para_buf:
            joined = " ".join(para_buf).strip()
            if joined:
                out.append(f"<p>{_render_inline(joined)}</p>")
            para_buf.clear()

    def _flush_list():
        nonlocal in_list
        if in_list:
            out.append(f"</{list_tag}>")
            in_list = False

    def _flush_bq():
        nonlocal in_blockquote
        if in_blockquote:
            out.append("</blockquote>")
            in_blockquote = False

    for raw in lines:
        line = raw.rstrip()

        # Fenced code
        if line.startswith("```"):
            if in_code:
                out.append("<pre><code>"
                           + html.escape("\n".join(code_buf))
                           + "</code></pre>")
                code_buf.clear()
                in_code = False
            else:
                _flush_para()
                _flush_list()
                _flush_bq()
                in_code = True
            continue
        if in_code:
            code_buf.append(raw)
            continue

        # Horizontal rule
        if re.match(r"^\s*-{3,}\s*$", line):
            _flush_para()
            _flush_list()
            _flush_bq()
            out.append("<hr>")
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            _flush_para()
            _flush_list()
            _flush_bq()
            level = len(m.group(1))
            content = _render_inline(html.escape(m.group(2)))
            out.append(f"<h{level}>{content}</h{level}>")
            continue

        # Blockquote
        m = re.match(r"^>\s?(.*)$", line)
        if m:
            _flush_para()
            _flush_list()
            if not in_blockquote:
                out.append("<blockquote>")
                in_blockquote = True
            body = _render_inline(html.escape(m.group(1)))
            out.append(f"<p>{body}</p>")
            continue
        else:
            _flush_bq()

        # Unordered list
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            _flush_para()
            if not in_list or list_tag != "ul":
                _flush_list()
                out.append("<ul>")
                in_list = True
                list_tag = "ul"
            body = _render_inline(html.escape(m.group(1)))
            out.append(f"<li>{body}</li>")
            continue

        # Ordered list
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            _flush_para()
            if not in_list or list_tag != "ol":
                _flush_list()
                out.append("<ol>")
                in_list = True
                list_tag = "ol"
            body = _render_inline(html.escape(m.group(1)))
            out.append(f"<li>{body}</li>")
            continue

        # Blank line ends paragraph/list
        if not line.strip():
            _flush_para()
            _flush_list()
            continue

        # Regular paragraph text
        _flush_list()
        para_buf.append(html.escape(line))

    # Cleanup
    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_buf))
                   + "</code></pre>")
    _flush_para()
    _flush_list()
    _flush_bq()
    return "\n".join(out)


def wrap_page(title: str, body_html: str) -> str:
    """Wrap an HTML fragment in a full page using the Dashboard's
    dark theme. Meant for `/gui/docs/*.md` display."""
    css = """
:root {
  --bg: #0f0f23; --bg2: #1a1a2e; --bg3: #16213e;
  --accent: #0f3460; --purple: #533483;
  --text: #e0e0e0; --text2: #a0a0b0;
  --blue: #4fc3f7; --green: #00d672;
  --red: #e94560; --yellow: #ffc107;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--text);
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  max-width: 900px; margin: 0 auto; padding: 24px;
  line-height: 1.6;
}
h1, h2, h3, h4 { color: var(--blue); margin-top: 24px; }
h1 { border-bottom: 1px solid var(--accent); padding-bottom: 8px; }
a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  background: var(--bg3); padding: 1px 6px; border-radius: 3px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
  font-size: 0.92em; color: var(--yellow);
}
pre {
  background: var(--bg2); border: 1px solid var(--accent);
  border-radius: 6px; padding: 12px; overflow-x: auto;
  margin: 12px 0;
}
pre code {
  background: transparent; padding: 0; color: var(--text);
  font-size: 0.9em; line-height: 1.5;
}
blockquote {
  border-left: 4px solid var(--purple);
  padding: 4px 12px; margin: 12px 0;
  background: var(--bg2);
  color: var(--text2);
}
hr { border: 0; border-top: 1px solid var(--accent); margin: 24px 0; }
ul, ol { padding-left: 28px; }
li { margin: 4px 0; }
strong { color: #fff; }
em { color: var(--text2); }
.docs-header {
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid var(--accent); padding-bottom: 8px;
  margin-bottom: 16px; font-size: 12px; color: var(--text2);
}
"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{css}</style>
</head>
<body>
<div class="docs-header">
  <span>arena-agent docs</span>
  <a href="javascript:history.back()">← Back to Dashboard</a>
</div>
{body_html}
</body>
</html>"""
