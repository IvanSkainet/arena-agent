#!/usr/bin/env bash
set -euo pipefail
REPORTS="${ARENA_AGENT_HOME:-$HOME/arena-agent}/reports"
mkdir -p "$REPORTS"
SESSION="${BACT_SESSION:-arena}"

stamp() { date -u +%Y%m%dT%H%M%SZ; }
slug()  { echo "$1" | sed -E 's#https?://##; s#[^A-Za-z0-9._-]+#_#g' | cut -c1-60; }

cmd="${1:-help}"; shift || true

case "$cmd" in
  help|--help|-h)
    cat <<'H'
Usage: agentctl bact <sub> [args]
  doctor                    check install + handshake
  extract <url> [args...]   stealth-extract URL as markdown
  shot <url>                stealth screenshot (PNG)
  open <url>                navigate (session: arena)
  state                     page state
  click <index>             click element by index
  type <text>               type text
  input <index> <text>      click + type
  eval <js>                 run JS, return result
  close                     close session
  auth {set <KEY>|clear|status}  manage browser-act API key
  browsers                  list configured browsers
  raw <args...>             pass-through to browser-act
H
    ;;
  doctor)
    command -v browser-act >/dev/null || { echo "browser-act not installed"; exit 1; }
    browser-act --version
    browser-act get-skills core --skill-version 2.0.0 >/dev/null && echo "handshake: ok"
    browser-act --format json browser list
    ;;
  extract)
    url="${1:?usage: extract <url>}"; shift || true
    out="$REPORTS/bact-extract-$(slug "$url")-$(stamp).md"
    browser-act --format json stealth-extract "$url" --output "$out" "$@" >/dev/null
    sz=$(wc -c <"$out" 2>/dev/null || echo 0)
    echo "saved: $out (${sz} bytes)"
    head -c 2000 "$out"
    [ "$sz" -gt 2000 ] && echo && echo "...(truncated, full file at $out)"
    ;;
  shot)
    url="${1:?usage: shot <url>}"; shift || true
    out="$REPORTS/bact-shot-$(slug "$url")-$(stamp).png"
    browser-act --format json --session "$SESSION" navigate "$url" >/dev/null
    browser-act --format json --session "$SESSION" screenshot "$out" --full
    echo "saved: $out"
    ;;
  open)   browser-act --format json --session "$SESSION" navigate "${1:?url}" ;;
  state)  browser-act --format json --session "$SESSION" state ;;
  click)  browser-act --format json --session "$SESSION" click "${1:?index}" ;;
  type)   browser-act --format json --session "$SESSION" type "${1:?text}" ;;
  input)  idx="${1:?index}"; shift; browser-act --format json --session "$SESSION" input "$idx" "$*" ;;
  eval)   browser-act --format json --session "$SESSION" eval "${1:?js}" ;;
  close)  browser-act --format json --session "$SESSION" session close "$SESSION" ;;
  auth)   sub="${1:-status}"; shift || true
          case "$sub" in
            set)    browser-act auth set "${1:?api key required}" ;;
            clear)  browser-act auth clear ;;
            status) test -f ~/.local/share/browseract/config.json && grep -q api_key ~/.local/share/browseract/config.json && echo "api_key: set" || echo "api_key: not set" ;;
            *)      echo "usage: bact auth {set <KEY>|clear|status}" >&2; exit 2 ;;
          esac ;;
  browsers) browser-act --format json browser list ;;
  raw)    browser-act "$@" ;;
  *)      echo "unknown subcommand: $cmd (try 'agentctl bact help')" >&2; exit 2 ;;
esac
