#!/usr/bin/env bash
# web/research — research по теме: DDG search → readability text топ-N сайтов →
# JSON-сводка + markdown отчёт в reports/.
#
# Usage: agentctl skill run web/research "тема" [количество_сайтов]
# Зависит от: py_browser.py (pure-Python, не требует chromium).
set -euo pipefail

QUERY="${1:?usage: web/research \"query\" [n=3]}"
N="${2:-3}"
OUT_DIR="${ARENA_AGENT_HOME:-$HOME/arena-agent}/reports"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
JSON_PATH="$OUT_DIR/research-${STAMP}.json"
MD_PATH="$OUT_DIR/research-${STAMP}.md"
PYB=/usr/bin/python3
SCRIPT="${ARENA_AGENT_HOME:-$HOME/arena-agent}/bin/py_browser.py"

# 1) Поиск
SEARCH_JSON=$("$PYB" "$SCRIPT" search "$QUERY" --n "$N")
echo "$SEARCH_JSON" > "$JSON_PATH.search"

# 2) Перебираем результаты и читаем каждый
{
  echo "# Research: $QUERY"
  echo
  echo "Generated: $(date -u --iso-8601=seconds)"
  echo
  echo "## Найденные источники"
  echo
} > "$MD_PATH"

python3 - "$JSON_PATH.search" "$MD_PATH" "$JSON_PATH" "$PYB" "$SCRIPT" <<'PY'
import json, sys, subprocess
search_file, md_path, json_path, pyb, script = sys.argv[1:6]
data = json.load(open(search_file))
results = data.get("results", [])
out = {"query": data.get("query"), "sources": []}

with open(md_path, "a", encoding="utf-8") as md:
    for i, r in enumerate(results, 1):
        url = r.get("url", "")
        title = r.get("title", "")
        md.write(f"### {i}. {title}\n\n")
        md.write(f"- URL: <{url}>\n")
        md.write(f"- Snippet: {r.get('snippet','')}\n\n")
        # вытаскиваем clean text
        try:
            p = subprocess.run([pyb, script, "read", url], capture_output=True, text=True, timeout=25)
            try:
                rd = json.loads(p.stdout)
                text = rd.get("text", "")
            except Exception:
                text = p.stdout[:3000]
        except Exception as e:
            text = f"(read failed: {e})"
        md.write("```\n" + (text[:2000] or "(no content)") + "\n```\n\n")
        out["sources"].append({"title": title, "url": url, "snippet": r.get("snippet",""), "text_preview": text[:1500]})

json.dump(out, open(json_path, "w"), ensure_ascii=False, indent=2)
PY

rm -f "$JSON_PATH.search"

echo "{\"ok\": true, \"query\": \"$QUERY\", \"sources\": $N, \"md\": \"$MD_PATH\", \"json\": \"$JSON_PATH\"}"
