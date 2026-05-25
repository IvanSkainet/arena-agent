# core/cleanup

Rotate / prune old data to keep the platform tidy.

## Inputs (optional flags)
- `--days N`     — age threshold (default 30)
- `--keep N`     — minimum items to keep per category (default 10)
- `--dry-run`    — show what would be deleted, do nothing
- `--apply`      — actually delete (default: dry-run)

## Categories cleaned
- `~/arena-agent/backups/`         — tarballs older than N days
- `~/arena-agent/memory/sessions/` — JSONL sessions older than N days
- `~/arena-agent/reports/`         — generated digests/reports older than N days
- `~/arena-agent/queue/done/`      — completed tasks older than N days
- `~/arena-agent/queue/failed/`    — failed tasks older than N days

Always keeps at least `--keep` newest items in each category, regardless of age.

## Outputs
- Summary per category: kept / pruned / freed-bytes
- Exit 0 always (cleanup is best-effort)
