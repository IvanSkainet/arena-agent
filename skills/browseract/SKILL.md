# browseract

Wrapper around the `browser-act` CLI for stealth-aware browser automation.

## Subcommands (via agentctl bact <sub>)

- doctor                 check install + handshake
- extract <url>          stealth-extract URL as markdown
- shot <url>             stealth screenshot (PNG)
- open <url>             start/use session, navigate
- state                  show current page state
- click <index>          click element by index
- type <text>            type into focused element
- input <index> <text>   click then type
- eval <js>              execute JS, return result
- close                  close current session
- raw <args...>          pass-through to browser-act

## When to use vs existing browser-* commands

- agentctl http <url> -- raw curl, no JS, cheapest
- agentctl readability <url> -- headless Chromium + Readability
- agentctl bact extract <url> -- stealth Chromium + anti-bot + markdown

## Boundaries

- Default = fully local. Bundled Chromium, no upload of cookies/page content.
- Cloud features (residential IPs, hosted CAPTCHA) require explicit
  `browser-act auth set <key>`. Not enabled by default.
- Reports saved to ~/arena-bridge/reports/bact-*
