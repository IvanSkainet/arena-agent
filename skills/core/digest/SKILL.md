# core/digest

Generate a compact markdown digest of the local Arena Agent state — suitable
for pasting into a brand-new Arena.ai chat to bootstrap context fast.

## Inputs
- argv[1] (optional): output file path. Default: `~/arena-agent/reports/digest-<UTC>.md`.

## Outputs
- Markdown file at the chosen path (chmod 600).
- The absolute path is printed to stdout.
- Sections included:
  - generated timestamp + hostname
  - bridge health + service state (short)
  - current project (if any)
  - last 8 memory facts
  - last task summary
  - last 5 reports (file names only)
  - last 10 chat sessions (file names only)
  - top-level command groups (chat / project / task / browser / recon / memory / skill)

## Notes
- Read-only. Safe to run any time.
- Designed to fit comfortably in a single Arena message (target < 6 KB).
