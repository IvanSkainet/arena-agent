# core/cleanup

Rotate / prune old data to keep the platform tidy.

## Inputs (optional flags)
- `--days N`     — age threshold (default 30)
- `--keep N`     — minimum items to keep per category (default 10)
- `--dry-run`    — show what would be deleted, do nothing
- `--apply`      — actually delete (default: dry-run)

## Categories cleaned
- `~/arena-bridge/backups/`         — tarballs older than N days
- `~/arena-bridge/memory/sessions/` — JSONL sessions older than N days
- `~/arena-bridge/reports/`         — generated digests/reports older than N days
- `~/arena-bridge/queue/done/`      — completed tasks older than N days
- `~/arena-bridge/queue/failed/`    — failed tasks older than N days
- `~/arena-bridge/logs/`            — rotated log files (`*.log.1`, `*.log.2`, `*.log.3`, `*.jsonl.1` – `*.jsonl.5`)

Always keeps at least `--keep` newest items in each category, regardless of age.

## Outputs
- Summary per category: kept / pruned / freed-bytes
- Exit 0 always (cleanup is best-effort)
