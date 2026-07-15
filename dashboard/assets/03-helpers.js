// ===== HELPERS =====
function esc(s) { const d = document.createElement("div"); d.textContent = String(s); return d.innerHTML; }
function relTime(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return Math.floor(diff) + "s ago";
    if (diff < 3600) return Math.floor(diff/60) + "m ago";
    if (diff < 86400) return Math.floor(diff/3600) + "h ago";
    return Math.floor(diff/86400) + "d ago";
  } catch(e) { return ts; }
}
function formatUptime(seconds) {
  if (!seconds && seconds !== 0) return "--";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return d + "d " + h + "h";
  if (h > 0) return h + "h " + m + "m";
  return m + "m";
}
function formatBytes(b) {
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b/1024).toFixed(1) + " KB";
  if (b < 1073741824) return (b/1048576).toFixed(1) + " MB";
  return (b/1073741824).toFixed(2) + " GB";
}
function setBar(id, pct, colorClass) {
  const bar = document.getElementById(id);
  const text = document.getElementById(id.replace("Bar","Text"));
  if (!bar) return;
  const p = Math.min(100, Math.max(0, pct));
  bar.style.width = p + "%";
  bar.className = "fill " + colorClass;
  if (p > 75 && colorClass !== "red") bar.className = "fill red";
  else if (p > 50 && colorClass === "green") bar.className = "fill yellow";
  if (text) text.textContent = p.toFixed(1) + "%";
}
function copyToClipboard(text) {
  try {
    navigator.clipboard.writeText(text).then(() => showCopyFeedback()).catch(() => {
      const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.left = "-9999px"; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); document.body.removeChild(ta); showCopyFeedback();
    });
  } catch(e) {}
}
function showCopyFeedback() {
  // brief visual feedback - handled per button
}

// Minimal Markdown -> HTML for Dashboard-embedded output. Same
// syntax subset that the server-side arena/gui/markdown_render.py
// supports: headings (# / ## / ###), bold **x**, italic *x*, inline
// code `x`, fenced code ```lang\n...\n```, links [t](u), unordered
// lists starting with * or - or +, horizontal rules ---, blockquotes >.
// Escapes HTML first, so no XSS. NOT a full CommonMark parser -- if
// you need one, use the /gui/docs/*.md endpoint (server-side).
function renderMarkdown(text) {
  if (text === null || text === undefined) return "";
  const s = String(text);
  const escaped = s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Fenced code blocks first (multi-line, greedy per fence).
  const blocks = [];
  let withoutFences = escaped.replace(/```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```/g,
    (_m, lang, code) => {
      const idx = blocks.length;
      blocks.push('<pre class="inset-block" style="overflow-x:auto"><code>'
                  + code.replace(/\n$/, "") + '</code></pre>');
      return "\u0000FENCE" + idx + "\u0000";
    });

  const lines = withoutFences.split("\n");
  const out = [];
  let inList = false;
  const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };

  for (let rawLine of lines) {
    let line = rawLine;

    // Horizontal rule
    if (/^\s*(---+|===+|\*\*\*+)\s*$/.test(line)) {
      closeList();
      out.push("<hr>");
      continue;
    }
    // Headings ###/##/#
    let m = line.match(/^(#{1,6})\s+(.+)$/);
    if (m) {
      closeList();
      const lvl = Math.min(m[1].length, 6);
      out.push(`<h${lvl} class="md-h${lvl}">${m[2]}</h${lvl}>`);
      continue;
    }
    // List item
    m = line.match(/^\s*[*+-]\s+(.+)$/);
    if (m) {
      if (!inList) { out.push('<ul style="margin:6px 0 6px 20px">'); inList = true; }
      out.push("<li>" + _mdInline(m[1]) + "</li>");
      continue;
    }
    // Blockquote
    if (/^\s*&gt;\s+/.test(line)) {
      closeList();
      out.push('<blockquote class="muted" style="border-left:3px solid var(--accent);padding-left:8px;margin:4px 0">'
               + _mdInline(line.replace(/^\s*&gt;\s+/, "")) + "</blockquote>");
      continue;
    }
    // Blank line
    if (line.trim() === "") {
      closeList();
      out.push("");
      continue;
    }
    // Plain paragraph line — inline-format and keep line breaks
    closeList();
    out.push(_mdInline(line));
  }
  closeList();

  let html = out.join("\n");
  // Restore fenced blocks
  html = html.replace(/\u0000FENCE(\d+)\u0000/g, (_m, i) => blocks[Number(i)]);
  // Collapse consecutive blank lines into paragraph breaks
  html = html.replace(/(?:\n\n+)/g, '<div style="height:6px"></div>');
  return html;
}

function _mdInline(s) {
  return s
    // inline code
    .replace(/`([^`\n]+)`/g,
             '<code style="background:var(--bg);padding:1px 4px;border-radius:3px">$1</code>')
    // links [text](url)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener">$1</a>')
    // bold **x**
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    // italic *x* (avoid mid-word asterisks)
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
}

