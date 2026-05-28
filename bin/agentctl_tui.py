#!/usr/bin/env python3
"""agentctl_tui.py — TUI control center на prompt_toolkit (Hermes-style).

Минималистичный текстовый UI: multiline input, slash-команды с autocomplete,
история, streaming-вывод. Бежит локально и шлёт команды напрямую в shell
(то есть имеет тот же доступ что и у пользователя — он же запускает её).

Запуск:  agentctl tui
Выход:   /quit  или  Ctrl-D
"""
from __future__ import annotations
import os, subprocess, sys, time
from pathlib import Path

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter, Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style
except ImportError as e:
    print(f"ERROR: prompt_toolkit not installed: {e}", file=sys.stderr)
    print("       pip install --user prompt_toolkit", file=sys.stderr)
    sys.exit(2)

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
HIST = ROOT / "logs" / "tui_history"
HIST.parent.mkdir(parents=True, exist_ok=True)

SLASH = {
    "/help":     "agentctl",
    "/sys":      "agentctl sys status",
    "/svc":      "systemctl --user --no-pager is-active arena-bridge arena-mcp-stream arena-mcp-ws arena-task-runner",
    "/health":   "curl -sS http://127.0.0.1:8765/health",
    "/tools":    "agentctl mcp stream-tools | python3 -m json.tool | head -40",
    "/shot":     "agentctl browser sd-shot ",
    "/search":   "agentctl browser py-search ",
    "/read":     "agentctl browser py-read ",
    "/skills":   "agentctl skill list",
    "/snap":     "agentctl skill run system/sys-snapshot",
    "/fix":      "agentctl skill run dev/auto-fix -- --dry",
    "/research": "agentctl skill run web/research ",
    "/hooks":    "agentctl hooks list",
    "/mem":      "agentctl mem get ",
    "/recall":   "python3 ~/arena-bridge/bin/memory_recall.py recall ",
    "/digest":   "python3 ~/arena-bridge/bin/memory_recall.py digest",
    "/backup":   "agentctl backup run",
    "/missions": "agentctl mission list",
    "/sub":      "python3 ~/arena-bridge/bin/subagent.py spawn ",
    "/subs":     "python3 ~/arena-bridge/bin/subagent.py list",
    "/cgroup":   "agentctl exec bash -c 'cat /proc/self/cgroup'",
    "/quit":     "__QUIT__",
    "/exit":     "__QUIT__",
    "/clear":    "__CLEAR__",
}


class SlashCompleter(Completer):
    """Подсказки только если строка начинается со /."""
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for k in sorted(SLASH.keys()):
            if k.startswith(text):
                yield Completion(k, start_position=-len(text), display_meta=SLASH[k][:50])


STYLE = Style.from_dict({
    "prompt":  "ansiblue bold",
    "rprompt": "ansibrightblack",
    "out":     "ansiwhite",
    "err":     "ansired",
    "ok":      "ansigreen",
    "hint":    "ansibrightblack italic",
    "meta":    "ansicyan",
})


def banner() -> None:
    print("\033[1;36m" + "═" * 70 + "\033[0m")
    print("\033[1;36m  🤖 Arena Agent — TUI v1\033[0m")
    print("\033[0;90m  Type /help for commands, /quit to exit, Tab for autocomplete\033[0m")
    print("\033[1;36m" + "═" * 70 + "\033[0m")


def expand_slash(text: str) -> str:
    text = text.strip()
    if not text.startswith("/"):
        return text
    for k in sorted(SLASH.keys(), key=lambda x: -len(x)):
        if text == k:
            return SLASH[k]
        if text.startswith(k + " "):
            return SLASH[k] + text[len(k) + 1:]
    return text


def run_shell(cmd: str) -> int:
    """Запуск команды локально с streaming-выводом."""
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
        p.wait()
        dur = time.time() - t0
        color = "\033[0;32m" if p.returncode == 0 else "\033[0;31m"
        print(f"{color}[exit={p.returncode}  {dur:.2f}s]\033[0m")
        return p.returncode
    except KeyboardInterrupt:
        print("\n\033[0;33m[interrupted]\033[0m")
        return 130


def main() -> int:
    banner()
    session = PromptSession(history=FileHistory(str(HIST)),
                            completer=SlashCompleter(),
                            style=STYLE, complete_while_typing=True,
                            multiline=False, mouse_support=True)
    bind = KeyBindings()

    while True:
        try:
            text = session.prompt(HTML("<prompt>arena ❯ </prompt>"),
                                   rprompt=HTML("<rprompt>Tab=autocomplete  /quit=exit</rprompt>"),
                                   key_bindings=bind)
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return 0

        text = text.strip()
        if not text:
            continue

        expanded = expand_slash(text)
        if expanded == "__QUIT__":
            print("bye.")
            return 0
        if expanded == "__CLEAR__":
            os.system("clear")
            continue
        if expanded != text:
            print(f"\033[0;90m(slash: {text}  →  {expanded})\033[0m")
        run_shell(expanded)


if __name__ == "__main__":
    sys.exit(main())
