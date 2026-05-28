# core/health

Fast platform health check. Designed to fit in under 1 KB output, so it's
cheap to run on every chat turn if desired.

## Inputs
- none

## Outputs (stdout)
- One line per check: `OK|FAIL  <component>  <detail>`
- Exit 0 if all green, 1 if any fail.

## Checks
- bridge HTTP (`127.0.0.1:8765/health`)
- arena-bridge.service active
- agentctl syntax check
- system python3 importable
- sessions dir present + 700
- facts.jsonl exists
- audit.jsonl writable
- disk free in $HOME (>= 1GB warn, >= 100MB error)
