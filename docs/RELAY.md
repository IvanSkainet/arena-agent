# Operator relay and persistent terminal ingress

`arena-relay` is a generic authenticated mailbox between a local operator or
program and an already-running agent session. It does **not** start, automate,
or impersonate an Arena.ai session.

## Configuration

```bash
export ARENA_BRIDGE_URL=http://127.0.0.1:8765
export ARENA_TOKEN=...                 # use your own bridge token
```

When `ARENA_TOKEN` is absent, the release-local `token.txt`,
`~/arena-bridge/token.txt`, then `~/.arena/token.txt` are checked. Never put a
token in a command committed to source control.

## Operator commands

```bash
arena-relay send "check the latest build"
arena-relay send --wait 120 "check it and reply"
arena-relay recv
arena-relay status
```

`send` queues durably even when no agent is polling. `send --wait` waits only
for a reply correlated to the new message. `status` distinguishes an active
poller from an idle queue rather than claiming delivery prematurely.

## Agent-side commands

```bash
arena-relay poll --wait 25
arena-relay reply MESSAGE_ID "done"
```

The HTTP equivalents are:

* `POST /v1/relay/send`
* `GET /v1/relay/poll?wait=N`
* `POST /v1/relay/reply`
* `GET /v1/relay/replies?in_reply_to=ID&wait=N`
* `GET /v1/relay/status`

A claim is exactly once. Replies carry `in_reply_to`, so concurrent callers do
not consume one another's acknowledgement.

## `arena-relay terminal`

Some local applications can notify an AI CLI only by pasting into its terminal.
Use the persistent adapter instead of writing an application-specific pseudo-CLI:

```bash
arena-relay terminal \
  --sender local-daemon \
  --source build-watcher \
  --reply-timeout 0
```

`--reply-timeout 0` waits indefinitely. A positive value returns to ready after
that many seconds without fabricating success.

For every submitted prompt the adapter:

1. accepts one ordinary line, one multiline bracketed paste, or a Windows
   ConPTY raw dispatch;
2. queues exactly one generic relay message with `transport=terminal`, `source`,
   and a monotonically increasing process-local `sequence`;
3. prints a busy marker and waits only for the correlated reply;
4. prints the reply and returns to `state: READY` for the next dispatch.

The process cannot summon an inactive agent. If no session polls the relay, the
message remains queued and the terminal remains honestly busy (or times out if
configured).

## Multiline and Windows ConPTY framing

Ordinary bracketed paste uses `ESC[200~ ... ESC[201~`, followed by Enter.
Windows ConPTY may strip those ESC markers and Windows line input truncates long
pastes. On a real Windows 10 host the truncation boundary was exactly 510
characters.

In Windows console mode the adapter therefore:

* temporarily enables raw virtual-terminal input and restores the previous mode
  on every exit path;
* decodes non-greedy binary chunks incrementally, preserving split UTF-8 and
  embedded CR/LF;
* accepts the host's leading Ctrl+U clear-input control as the start of one raw
  dispatch;
* accepts a delayed newline-only chunk as the final Submit event;
* echoes a bounded printable prefix for hosts that require visibility proof
  before sending Enter;
* rearms the visibility echo at each Ctrl+U boundary.

Incomplete bracketed or raw dispatches are never delivered. Prompt content is
bounded to 256 KiB; visibility echo is separately bounded to 1 KiB. The adapter
contains no paths, schemas, rules, or completion files from any application.

## Integration checklist

1. Configure the local program to launch `arena-relay terminal` in its persistent
   CLI/ConPTY slot.
2. Start an agent poll before dispatch when immediate handling is required.
3. Send one real multiline application packet, not a one-line test substitute.
4. Verify the relay body exactly, including embedded newlines.
5. Post a correlated reply and verify the local CLI returns to ready.
6. Dispatch a second packet in the same process to prove rearming.
7. Exercise the application's validation-error/repair path if it has one.
8. Confirm final inbox and reply depths return to zero.

The live Book of Eternity stress run applying this checklist is recorded in
[`scenarios/BOOK_OF_ETERNITY_DAEMON_E2E.md`](scenarios/BOOK_OF_ETERNITY_DAEMON_E2E.md).
That game is a scenario for this transport, not part of the transport contract.

---

## Кратко по-русски

`arena-relay` — аутентифицированный mailbox между локальной программой и уже
работающей агентской сессией. Команда `terminal` держит постоянный CLI-вход,
собирает весь multiline prompt в **одно** сообщение, ждёт коррелированный reply
и только после него возвращается в `READY`. Она не запускает Arena-сессию и не
добавляет в мост правила вызывающего приложения.

Для Windows ConPTY поддержан реально наблюдённый raw-протокол: Ctrl+U задаёт
начало dispatch, внутренние переводы строк сохраняются, а отдельный отложенный
Enter завершает пакет. Исходный console mode всегда восстанавливается,
незавершённые пакеты не доставляются, prompt ограничен 256 KiB, handshake echo —
1 KiB. Для live-проверки обязательны два последовательных multiline dispatch в
одном процессе и настоящий validation/repair цикл вызывающего приложения.
